import logging
from typing import Dict, Any, Optional, TypedDict, List

from anyio.streams.memory import MemoryObjectSendStream

from trpc_agent.application import FSMApplication
from llm.utils import AsyncLLM, get_llm_client
from llm.common import Message, TextRaw
from api.fsm_tools import FSMToolProcessor
from core.statemachine import MachineCheckpoint
from uuid import uuid4

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
)
from api.agent_server.interface import AgentInterface

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    fsm_state: MachineCheckpoint


class TrpcAgentSession(AgentInterface):
    def __init__(self, application_id: str | None= None, trace_id: str | None = None, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""
        self.application_id = application_id or uuid4().hex
        self.trace_id = trace_id or uuid4().hex
        self.settings = settings or {}
        self.processor_instance = FSMToolProcessor(FSMApplication)
        self.llm_client: AsyncLLM = get_llm_client()
        self.model_params = {
            "max_tokens": 8192,
        }

    async def get_app_diff(self) -> str:
        fsm_app = self.processor_instance.fsm_app
        match fsm_app:
            case None:
                raise ValueError("FSMApplication is None")
            case FSMApplication():
                ctx = fsm_app.fsm.context

        files = fsm_app.get_files_at_root(ctx)
        diff = await fsm_app.get_diff_with(files)
        return diff

    @staticmethod
    def user_answered(messages: List[Message]) -> bool:
        if not messages:
              return False
        return messages[-1].role == "user"

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the incoming request and send events to the event stream.
        This is the main method required by the AgentInterface protocol.

        Args:
            request: Incoming agent request
            event_tx: Event transmission stream
        """
        try:
            logger.info(f"Processing request for {self.application_id}:{self.trace_id}")

            # Check if we need to initialize or if this is a continuation with an existing state
            if request.agent_state:
                logger.info(f"Continuing with existing state for trace {self.trace_id}")
                fsm_state = request.agent_state.get("fsm_state")
                match fsm_state:
                    case None:
                        self.processor_instance = FSMToolProcessor(FSMApplication)
                    case _:
                        fsm = await FSMApplication.load(fsm_state)
                        self.processor_instance = FSMToolProcessor(FSMApplication, fsm_app=fsm)
            else:
                logger.info(f"Initializing new session for trace {self.trace_id}")

            # Process the initial step
            # TODO: Convert messages properly
            messages = [
                Message(role=m.role if m.role == "user" else "assistant", content=[TextRaw(text=m.content)])
                for m in request.all_messages
            ]


            while True:
                new_messages = await self.processor_instance.step(messages, self.llm_client, self.model_params)
                if self.processor_instance.fsm_app is None:
                    logger.info("FSMApplication is empty")
                    fsm_state = None
                    app_diff = None
                    # this is legit if we did not start a FSM as initial message is not informative enough (e.g. just 'hello')
                else:
                    fsm_state = await self.processor_instance.fsm_app.fsm.dump()
                    app_diff = await self.get_app_diff()
                event_out = AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        role="agent",
                        kind=MessageKind.STAGE_RESULT,
                        content=str(new_messages),
                        agentState={"fsm_state": fsm_state} if fsm_state else None,
                        unifiedDiff=app_diff
                    )
                )
                await event_tx.send(event_out)
                messages += new_messages

                match self.processor_instance.fsm_app:
                    case None:
                        is_completed = False
                    case FSMApplication():
                        fsm_app = self.processor_instance.fsm_app
                        is_completed = fsm_app.is_completed

                if not self.user_answered(new_messages) or is_completed:
                    break


        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            error_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing request: {str(e)}",
                    agentState=None,
                    unifiedDiff=None
                )
            )
            await event_tx.send(error_event)
        finally:
            await event_tx.aclose()
