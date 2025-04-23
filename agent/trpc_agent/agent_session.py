import logging
from typing import Dict, Any, Optional, TypedDict, List

from anyio.streams.memory import MemoryObjectSendStream

from trpc_agent.application import FSMApplication, FSMState
from llm.utils import AsyncLLM, get_llm_client
from llm.common import Message, TextRaw
from api.fsm_tools import FSMToolProcessor
from core.statemachine import MachineCheckpoint
from uuid import uuid4
import ujson as json

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
                # We intentionally generate the diff against an *empty* snapshot.
                # Passing the current files as the snapshot results in an empty diff
                # (because the snapshot and the final state are identical).
                # Using an empty snapshot correctly produces a diff that contains
                # all files that have been generated or modified in the current
                # FSM state.
                snapshot: dict[str, str] = {}

        logger.info(
            "Generating diff with %s files in state %s compared to empty snapshot",
            len(fsm_app.get_files_at_root(fsm_app.fsm.context)),
            fsm_app.current_state,
        )

                # We intentionally generate the diff against an *empty* snapshot.
                # Passing the current files as the snapshot results in an empty diff
                # (because the snapshot and the final state are identical).
                # Using an empty snapshot correctly produces a diff that contains
                # all files that have been generated or modified in the current
                # FSM state.
                snapshot: dict[str, str] = {}

        logger.info(
            "Generating diff with %s files in state %s compared to empty snapshot",
            len(fsm_app.get_files_at_root(fsm_app.fsm.context)),
            fsm_app.current_state,
        )

        try:
            diff = await fsm_app.get_diff_with(snapshot)
            # Log the diff length to help diagnose issues
            if diff:
                logger.info("Generated diff with length %d", len(diff))
            else:
                logger.warning("Generated empty diff")
            return diff
        except Exception as e:
            logger.exception(f"Error generating diff: {e}")
            return f"Error generating diff: {e}"

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
                    # include empty diffs too as they are valid = template diff
                messages += new_messages
                event_out = AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        role="assistant",
                        kind=MessageKind.STAGE_RESULT if self.user_answered(messages) else MessageKind.REFINEMENT_REQUEST,
                        content=json.dumps([x.to_dict() for x in messages] ),
                        agentState={"fsm_state": fsm_state} if fsm_state else None,
                        unifiedDiff=app_diff
                    )
                )
                await event_tx.send(event_out)

                match self.processor_instance.fsm_app:
                    case None:
                        is_completed = False
                    case FSMApplication():
                        fsm_app = self.processor_instance.fsm_app
                        is_completed = fsm_app.is_completed

                # If the FSM is completed, ensure the diff is sent properly
                if is_completed:
                    try:
                        # This is the final state - make sure we produce a proper diff
                        if self.processor_instance.fsm_app and self.processor_instance.fsm_app.current_state == FSMState.COMPLETE:
                            logger.info(f"Sending final state diff for trace {self.trace_id}")
                            
                            # Get final context and files
                            #ctx = self.processor_instance.fsm_app.fsm.context
                            #files = self.processor_instance.fsm_app.get_files_at_root(ctx)
                            # Get and send a final diff specifically for the completion state
                            #final_diff = await self.processor_instance.fsm_app.get_diff_with(files)
                            
                            # We purposely generate diff against an empty snapshot to ensure
                            # that *all* generated files are included in the final diff. Using
                            # the current files as the snapshot would yield an empty diff.
                            final_diff = await self.processor_instance.fsm_app.get_diff_with({})
                           
                            # Always include a diff in the final state, even if empty
                            if not final_diff:
                                final_diff = "# Note: This is a valid empty diff (means no changes from template)"
                            
                            completion_event = AgentSseEvent(
                                status=AgentStatus.IDLE,
                                traceId=self.trace_id,
                                message=AgentMessage(
                                    role="assistant",
                                    kind=MessageKind.STAGE_RESULT,
                                    content=json.dumps([x.to_dict() for x in messages]),
                                    agentState={"fsm_state": fsm_state} if fsm_state else None,
                                    unifiedDiff=final_diff
                                )
                            )
                            logger.info(f"Sending completion event with diff (length: {len(final_diff)})")
                            await event_tx.send(completion_event)
                    except Exception as e:
                        logger.exception(f"Error sending final diff: {e}")

                if not self.user_answered(new_messages) or is_completed:
                    break


        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            error_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing request: {str(e)}",
                    agentState=None,
                    unifiedDiff=None
                )
            )
            await event_tx.send(error_event)
        finally:
            await event_tx.aclose()
