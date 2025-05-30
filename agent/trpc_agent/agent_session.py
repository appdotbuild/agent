import logging
from typing import Dict, Any, Optional, TypedDict, List, Union

from anyio.streams.memory import MemoryObjectSendStream

from llm.common import Message, TextRaw
from trpc_agent.application import FSMApplication
from llm.utils import AsyncLLM, get_llm_client
from api.fsm_tools import FSMToolProcessor, FSMStatus
from api.snapshot_utils import snapshot_saver
from core.statemachine import MachineCheckpoint
from uuid import uuid4
import dagger
import ujson as json

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
)
from api.agent_server.interface import AgentInterface
from llm.llm_generators import generate_app_name, generate_commit_message

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    fsm_state: MachineCheckpoint


class TrpcAgentSession(AgentInterface):
    def __init__(self, client: dagger.Client, application_id: str | None= None, trace_id: str | None = None, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""
        self.application_id = application_id or uuid4().hex
        self.trace_id = trace_id or uuid4().hex
        self.settings = settings or {}
        self.processor_instance = FSMToolProcessor(client, FSMApplication)
        self.llm_client: AsyncLLM = get_llm_client()
        self.model_params = {
            "max_tokens": 8192,
        }
        self._template_diff_sent: bool = False
        self.client = client

    @staticmethod
    def convert_agent_messages_to_llm_messages(agent_messages: List[AgentMessage]) -> List[Message]:
        """Convert AgentMessage list to LLM Message format."""
        return [
            Message(
                role=m.role if m.role == "user" else "assistant",
                content=[TextRaw(text=m.content)]
            )
            for m in agent_messages
        ]

    @staticmethod
    def prepare_snapshot_from_request(request: AgentRequest) -> Dict[str, str]:
        """Prepare snapshot files from request.all_files."""
        snapshot_files = {}
        if request.all_files:
            for file_entry in request.all_files:
                snapshot_files[file_entry.path] = file_entry.content
        return snapshot_files

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
                        self.processor_instance = FSMToolProcessor(self.client, FSMApplication)
                    case _:
                        fsm = await FSMApplication.load(self.client, fsm_state)
                        self.processor_instance = FSMToolProcessor(self.client, FSMApplication, fsm_app=fsm)
            else:
                logger.info(f"Initializing new session for trace {self.trace_id}")

            if self.processor_instance.fsm_app is not None:
                snapshot_saver.save_snapshot(
                    trace_id=self.trace_id,
                    key="fsm_enter",
                    data=await self.processor_instance.fsm_app.fsm.dump(),
                )

            # Process the initial step
            messages = self.convert_agent_messages_to_llm_messages(request.all_messages)

            flash_lite_client = get_llm_client(model_name="gemini-flash-lite")
            top_level_agent_llm = get_llm_client(model_name="gemini-flash")

            work_in_progress = False
            while True:
                new_messages, fsm_status = await self.processor_instance.step(messages, top_level_agent_llm, self.model_params)
                work_in_progress = fsm_status == FSMStatus.WIP

                fsm_state = None
                if self.processor_instance.fsm_app is None:
                    logger.info("FSMApplication is empty")
                    # this is legit if we did not start a FSM as initial message is not informative enough (e.g. just 'hello')
                else:
                    fsm_state = await self.processor_instance.fsm_app.fsm.dump()

                # TODO: avoid sending all messages back - send only new messages
                messages += new_messages

                app_name = None
                # Send initial template diff if we are not working on a FSM and we are not restoring a previous state
                #FIXME: simplify this condition and write unit test for this
                if (not self._template_diff_sent
                    and request.agent_state is None
                    and self.processor_instance.fsm_app):

                    prompt = self.processor_instance.fsm_app.fsm.context.user_prompt
                    app_name = await generate_app_name(prompt, flash_lite_client)
                    # Communicate the app name and commit message and template diff to the client
                    initial_template_diff = await self.processor_instance.fsm_app.get_diff_with({})

                    # Mark template diff as sent so subsequent iterations do not resend it.
                    self._template_diff_sent = True

                    #TODO: move into FSM in intial state to control this?
                    await self.send_event(
                        event_tx=event_tx,
                        status=AgentStatus.RUNNING,
                        kind=MessageKind.REVIEW_RESULT,
                        content=messages,
                        fsm_state=fsm_state,
                        unified_diff=initial_template_diff,
                        app_name=app_name,
                        commit_message="Initial commit"
                    )

                # Send event based on FSM status
                match fsm_status:
                    case FSMStatus.WIP:
                        await self.send_event(
                            event_tx=event_tx,
                            status=AgentStatus.RUNNING,
                            kind=MessageKind.STAGE_RESULT,
                            content=messages,
                            fsm_state=fsm_state,
                            app_name=app_name,
                        )
                    case FSMStatus.REFINEMENT_REQUEST:
                        await self.send_event(
                            event_tx=event_tx,
                            status=AgentStatus.IDLE,
                            kind=MessageKind.REFINEMENT_REQUEST,
                            content=messages,
                            fsm_state=fsm_state,
                            app_name=app_name,
                        )
                    case FSMStatus.FAILED:
                        await self.send_event(
                            event_tx=event_tx,
                            status=AgentStatus.IDLE,
                            kind=MessageKind.RUNTIME_ERROR,
                            content=messages,
                        )
                    case FSMStatus.COMPLETED:
                        try:
                            logger.info("FSM is completed")

                            #TODO: write unit test for this
                            snapshot_files = self.prepare_snapshot_from_request(request)
                            final_diff = await self.processor_instance.fsm_app.get_diff_with(snapshot_files)

                            logger.info(
                                "Sending completion event with diff (length: %d) for state %s",
                                len(final_diff) if final_diff else 0,
                                self.processor_instance.fsm_app.current_state,
                            )

                            prompt = self.processor_instance.fsm_app.fsm.context.user_prompt
                            commit_message = await generate_commit_message(prompt, flash_lite_client)

                            await self.send_event(
                                event_tx=event_tx,
                                status=AgentStatus.IDLE,
                                kind=MessageKind.REVIEW_RESULT,
                                content=messages,
                                fsm_state=fsm_state,
                                unified_diff=final_diff,
                                app_name=app_name,
                                commit_message=commit_message
                            )
                        except Exception as e:
                            logger.exception(f"Error sending final diff: {e}")

                # Exit if we are not working on a FSM or if the FSM is completed or failed
                if fsm_status != FSMStatus.WIP:
                    break

        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            await self.send_event(
                event_tx=event_tx,
                status=AgentStatus.IDLE,
                kind=MessageKind.RUNTIME_ERROR,
                content=f"Error processing request: {str(e)}"
            )
        finally:
            if self.processor_instance.fsm_app is not None:
                snapshot_saver.save_snapshot(
                    trace_id=self.trace_id,
                    key="fsm_exit",
                    data=await self.processor_instance.fsm_app.fsm.dump(),
                )
            await event_tx.aclose()

    # ---------------------------------------------------------------------
    # Event sending helpers
    # ---------------------------------------------------------------------
    async def send_event(
        self,
        event_tx: MemoryObjectSendStream[AgentSseEvent],
        status: AgentStatus,
        kind: MessageKind,
        content: Union[List[Message], str],
        fsm_state: Optional[MachineCheckpoint] = None,
        unified_diff: Optional[str] = None,
        app_name: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> None:
        """Send event with specified parameters."""
        # Handle content serialization based on type
        if isinstance(content, list):
            # Messages need to be serialized to JSON
            content_str = json.dumps([x.to_dict() for x in content], sort_keys=True)
        else:
            # Error messages are already strings
            content_str = content

        event = AgentSseEvent(
            status=status,
            traceId=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=kind,
                content=content_str,
                agentState={"fsm_state": fsm_state} if fsm_state else None,
                unifiedDiff=unified_diff,
                complete_diff_hash=None,
                diff_stat=None,
                app_name=app_name,
                commit_message=commit_message
            )
        )
        await event_tx.send(event)
