import logging
from typing import Dict, Any, Optional, TypedDict, List

from anyio.streams.memory import MemoryObjectSendStream

from llm.common import Message, TextRaw
from trpc_agent.application import FSMApplication
from llm.utils import AsyncLLM, get_llm_client
from api.fsm_tools import FSMToolProcessor, FSMStatus
from api.snapshot_utils import snapshot_saver
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
from trpc_agent.diff_utils import compute_diff_stat
from trpc_agent.llm_generators import generate_app_name, generate_commit_message

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
        self._template_diff_sent: bool = False

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
            len(fsm_app.fsm.context.files),
            fsm_app.current_state,
        )

        try:
            diff = await fsm_app.get_diff_with(snapshot)
            if diff:
                logger.info(
                    "Generated diff: length=%d",
                    len(diff),
                )
            else:
                logger.warning("Generated empty diff")
            return diff
        except Exception as e:
            logger.exception(f"Error generating diff: {e}")
            return f"Error generating diff: {e}"

    
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
    
    async def send_checkpoint_event(
        self,
        event_tx: MemoryObjectSendStream[AgentSseEvent],
        messages: List[Message],
        kind: MessageKind,
        fsm_state: Optional[MachineCheckpoint] = None,
        unified_diff: Optional[str] = None,
        app_name: Optional[str] = None,
        commit_message: Optional[str] = None,
    ) -> None:
        """Helper method to send events with consistent structure."""
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            traceId=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=kind,
                content=json.dumps([x.to_dict() for x in messages], sort_keys=True),
                agentState={"fsm_state": fsm_state} if fsm_state else None,
                unifiedDiff=unified_diff,
                complete_diff_hash=None,
                diff_stat=compute_diff_stat(unified_diff) if unified_diff else None,
                app_name=app_name,
                commit_message=commit_message
            )
        )
        await event_tx.send(event)
    
    async def send_error_event(
        self,
        event_tx: MemoryObjectSendStream[AgentSseEvent],
        error_message: str,
    ) -> None:
        """Helper method to send error events."""
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            traceId=self.trace_id,
            message=AgentMessage(
                role="assistant",
                kind=MessageKind.RUNTIME_ERROR,
                content=error_message,
                agentState=None,
                unifiedDiff=None,
                complete_diff_hash=None,
                diff_stat=None,
                app_name=None,
                commit_message=None
            )
        )
        await event_tx.send(event)
        
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

            if self.processor_instance.fsm_app is not None:
                snapshot_saver.save_snapshot(
                    trace_id=self.trace_id,
                    key="fsm_enter",
                    data=await self.processor_instance.fsm_app.fsm.dump(),
                )

            # Process the initial step
            messages = self.convert_agent_messages_to_llm_messages(request.all_messages)

            work_in_progress = False
            while True:
                new_messages, fsm_status = await self.processor_instance.step(messages, self.llm_client, self.model_params)
                work_in_progress = fsm_status == FSMStatus.WIP

                fsm_state = None
                if self.processor_instance.fsm_app is None:
                    logger.info("FSMApplication is empty")
                    # this is legit if we did not start a FSM as initial message is not informative enough (e.g. just 'hello')
                else:
                    fsm_state = await self.processor_instance.fsm_app.fsm.dump()
                    #app_diff = await self.get_app_diff() # TODO: implement diff stats after optimizations

                messages += new_messages

                app_name = None
                commit_message = None
                if (not self._template_diff_sent
                    and request.agent_state is None
                    and self.processor_instance.fsm_app):
                    prompt = self.processor_instance.fsm_app.fsm.context.user_prompt
                    flash_lite_client = get_llm_client(model_name="gemini-flash-lite")
                    app_name = await generate_app_name(prompt, flash_lite_client)
                    # Communicate the app name and commit message and template diff to the client
                    initial_template_diff = await self.get_app_diff()

                    # Mark template diff as sent so subsequent iterations do not resend it.
                    self._template_diff_sent = True

                    await self.send_checkpoint_event(
                        event_tx=event_tx,
                        messages=messages,
                        kind=MessageKind.REVIEW_RESULT,
                        fsm_state=fsm_state,
                        unified_diff=initial_template_diff,
                        app_name=app_name,
                        commit_message="Initial commit"
                    )
                    commit_message = await generate_commit_message(prompt, flash_lite_client)

                await self.send_checkpoint_event(
                    event_tx=event_tx,
                    messages=messages,
                    kind=MessageKind.STAGE_RESULT if work_in_progress else MessageKind.REFINEMENT_REQUEST,
                    fsm_state=fsm_state,
                    app_name=app_name,
                    commit_message=commit_message
                )

                match self.processor_instance.fsm_app:
                    case None:
                        is_completed = False
                    case FSMApplication():
                        fsm_app = self.processor_instance.fsm_app
                        is_completed = fsm_app.is_completed

                if is_completed:
                    try:
                        logger.info(f"FSM is completed: {is_completed}")

                        snapshot_files = self.prepare_snapshot_from_request(request)
                        final_diff = await self.processor_instance.fsm_app.get_diff_with(snapshot_files)

                        logger.info(
                            "Sending completion event with diff (length: %d) for state %s",
                            len(final_diff) if final_diff else 0,
                            self.processor_instance.fsm_app.current_state,
                        )
                        
                        await self.send_checkpoint_event(
                            event_tx=event_tx,
                            messages=messages,
                            kind=MessageKind.REVIEW_RESULT,
                            fsm_state=fsm_state,
                            unified_diff=final_diff,
                            app_name=app_name,
                            commit_message=commit_message
                        )
                    except Exception as e:
                        logger.exception(f"Error sending final diff: {e}")

                if not work_in_progress or is_completed:
                    break

        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            await self.send_error_event(
                event_tx=event_tx,
                error_message=f"Error processing request: {str(e)}"
            )
        finally:
            if self.processor_instance.fsm_app is not None:
                snapshot_saver.save_snapshot(
                    trace_id=self.trace_id,
                    key="fsm_exit",
                    data=await self.processor_instance.fsm_app.fsm.dump(),
                )
            await event_tx.aclose()
