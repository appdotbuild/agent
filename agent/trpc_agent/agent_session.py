import logging
from typing import Dict, Any, Optional, TypedDict, List

from anyio.streams.memory import MemoryObjectSendStream

from trpc_agent.application import FSMApplication
from llm.utils import AsyncLLM, get_llm_client
from llm.common import Message, TextRaw
from api.fsm_tools import FSMToolProcessor, FSMStatus
from core.statemachine import MachineCheckpoint
from uuid import uuid4
import ujson as json

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
    DiffStatEntry,
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
        self._prev_diff_hash: Optional[str] = None  # sha256 of last complete diff sent

        # Track whether the initial template diff has already been sent for this session.
        # The template diff is a large unified diff between the generated project (at draft stage)
        # and an empty snapshot. We only want to send it once per session to avoid duplicating
        # large payloads on every iteration when the state has not changed.
        self._template_diff_sent: bool = False

        # Cache mapping FSM state name -> diff hash that was last sent for that state. This lets
        # us avoid re-computing and re-sending identical diffs when the agent remains in the same
        # state and no underlying file changes have occurred (e.g. during multiple refinement
        # passes where the code has not changed).
        self._state_diff_hash: Dict[str, str] = {}

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
    async def generate_app_name(prompt: str, llm_client: AsyncLLM) -> str:
        """Generate a GitHub repository name from the application description"""
        try:
            logger.info(f"Generating app name from prompt: {prompt[:50]}...")

            messages = [
                Message(role="user", content=[
                    TextRaw(f"""Based on this application description, generate a short, concise name suitable for use as a GitHub repository name.
The name should be lowercase with words separated by hyphens (kebab-case) and should not include any special characters.
Application description: "{prompt}"
Return ONLY the name, nothing else.""")
                ])
            ]

            completion = await llm_client.completion(
                messages=messages,
                max_tokens=50,
                temperature=0.7
            )

            generated_name = ""
            for block in completion.content:
                if isinstance(block, TextRaw):
                    name = block.text.strip().strip('"\'').lower()
                    import re
                    name = re.sub(r'[^a-z0-9\-]', '-', name.replace(' ', '-').replace('_', '-'))
                    name = re.sub(r'-+', '-', name)
                    name = name.strip('-')
                    generated_name = name
                    break

            if not generated_name:
                logger.warning("Failed to generate app name, using default")
                return "generated-application"

            logger.info(f"Generated app name: {generated_name}")
            return generated_name
        except Exception as e:
            logger.exception(f"Error generating app name: {e}")
            return "generated-application"

    @staticmethod
    async def generate_commit_message(prompt: str, llm_client: AsyncLLM) -> str:
        """Generate a Git commit message from the application description"""
        try:
            logger.info(f"Generating commit message from prompt: {prompt[:50]}...")

            messages = [
                Message(role="user", content=[
                    TextRaw(f"""Based on this application description, generate a concise Git commit message that follows best practices.
The message should be clear, descriptive, and follow conventional commit format.
Application description: "{prompt}"
Return ONLY the commit message, nothing else.""")
                ])
            ]

            completion = await llm_client.completion(
                messages=messages,
                max_tokens=100,
                temperature=0.7
            )

            commit_message = ""
            for block in completion.content:
                if isinstance(block, TextRaw):
                    message = block.text.strip().strip('"\'')
                    commit_message = message
                    break

            if not commit_message:
                logger.warning("Failed to generate commit message, using default")
                return "Initial commit"

            logger.info(f"Generated commit message: {commit_message}")
            return commit_message
        except Exception as e:
            logger.exception(f"Error generating commit message: {e}")
            return "Initial commit"

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

            work_in_progress = False
            while True:
                new_messages, fsm_status = await self.processor_instance.step(messages, self.llm_client, self.model_params)
                work_in_progress = fsm_status == FSMStatus.WIP

                current_hash: Optional[str] = None
                diff_stat: Optional[List[DiffStatEntry]] = []

                fsm_state = None
                app_diff = None
                if self.processor_instance.fsm_app is None:
                    logger.info("FSMApplication is empty")
                    # this is legit if we did not start a FSM as initial message is not informative enough (e.g. just 'hello')
                else:
                    fsm_state = await self.processor_instance.fsm_app.fsm.dump()
                    # Always compute app_diff and diff_stat if FSMApplication is present
                    app_diff = await self.get_app_diff()
                    current_hash = self._hash_diff(app_diff) if app_diff is not None else None
                    diff_changed = current_hash != self._prev_diff_hash if current_hash is not None else False
                    diff_stat = self._compute_diff_stat(app_diff) if app_diff is not None else None

                    if diff_changed:
                        self._prev_diff_hash = current_hash
                    # include empty diffs too as they are valid = template diff (when diff_to_send not null)
                messages += new_messages

                app_name = None
                commit_message = None
                if (not self._template_diff_sent
                    and request.agent_state is None
                    and self.processor_instance.fsm_app):
                    prompt = self.processor_instance.fsm_app.fsm.context.user_prompt
                    flash_lite_client = get_llm_client(model_name="gemini-flash-lite")
                    app_name = await self.generate_app_name(prompt, flash_lite_client)
                    # Communicate the app name and commit message and template diff to the client
                    initial_template_diff = await self.get_app_diff()

                    # Mark template diff as sent so subsequent iterations do not resend it.
                    self._template_diff_sent = True

                    event_out = AgentSseEvent(
                        status=AgentStatus.IDLE,
                        traceId=self.trace_id,
                        message=AgentMessage(
                            role="assistant",
                            kind=MessageKind.REVIEW_RESULT,
                            content=json.dumps([x.to_dict() for x in messages], sort_keys=True),
                            agentState={"fsm_state": fsm_state} if fsm_state else None,
                            unifiedDiff=initial_template_diff,
                            complete_diff_hash=current_hash,
                            diff_stat=diff_stat,
                            app_name=app_name,
                            commit_message="Initial commit"
                        )
                    )
                    await event_tx.send(event_out)
                    commit_message = await self.generate_commit_message(prompt, flash_lite_client)

                event_out = AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        role="assistant",
                        kind=MessageKind.STAGE_RESULT if work_in_progress else MessageKind.REFINEMENT_REQUEST,
                        content=json.dumps([x.to_dict() for x in messages], sort_keys=True),
                        agentState={"fsm_state": fsm_state} if fsm_state else None,
                        unifiedDiff=None,
                        complete_diff_hash=current_hash,
                        diff_stat=diff_stat,
                        app_name=app_name,
                        commit_message=commit_message
                    )
                )
                await event_tx.send(event_out)

                match self.processor_instance.fsm_app:
                    case None:
                        is_completed = False
                    case FSMApplication():
                        fsm_app = self.processor_instance.fsm_app
                        is_completed = fsm_app.is_completed

                if is_completed:
                    try:
                        logger.info(f"FSM is completed: {is_completed}")

                        # Prepare snapshot from request.all_files if available
                        snapshot_files = {}
                        if request.all_files:
                            for file_entry in request.all_files:
                                snapshot_files[file_entry.path] = file_entry.content

                        final_diff = await self.processor_instance.fsm_app.get_diff_with(snapshot_files)

                        diff_hash = self._hash_diff(final_diff)

                        # Skip setting diff hash for this state if it has already been emitted
                        skip_diff = False
                        if self._state_diff_hash.get(self.processor_instance.fsm_app.current_state) == diff_hash:
                            logger.info(
                                "Diff for state %s unchanged (hash=%s), skipping duplicate event",
                                self.processor_instance.fsm_app.current_state,
                                diff_hash,
                            )
                            skip_diff = True
                        else:
                            # Cache hash for this state to prevent future duplicates
                            self._state_diff_hash[self.processor_instance.fsm_app.current_state] = diff_hash

                        completion_event = AgentSseEvent(
                            status=AgentStatus.IDLE,
                            traceId=self.trace_id,
                            message=AgentMessage(
                                role="assistant",
                                kind=MessageKind.REVIEW_RESULT,
                                content=json.dumps([x.to_dict() for x in messages], sort_keys=True),
                                agentState={"fsm_state": fsm_state} if fsm_state else None,
                                unifiedDiff=None if skip_diff else final_diff,
                                complete_diff_hash=diff_hash,
                                diff_stat=self._compute_diff_stat(final_diff),
                                app_name=app_name,
                                commit_message=commit_message
                            )
                        )
                        logger.info(
                            "Sending completion event with diff (length: %d) for state %s",
                            len(final_diff),
                            self.processor_instance.fsm_app.current_state,
                        )
                        await event_tx.send(completion_event)
                    except Exception as e:
                        logger.exception(f"Error sending final diff: {e}")

                if not work_in_progress or is_completed:
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
                    unifiedDiff=None,
                    app_name=None,
                    commit_message=None
                )
            )
            await event_tx.send(error_event)
        finally:
            await event_tx.aclose()

    # ---------------------------------------------------------------------
    # Diff helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _hash_diff(diff: str) -> str:
        import hashlib
        return hashlib.sha256(diff.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_diff_stat(diff: str) -> List[DiffStatEntry]:
        """Return a list of DiffStatEntry parsed from a unified diff string."""
        stats: dict[str, Dict[str, int]] = {}
        current_file: Optional[str] = None

        for line in diff.splitlines():
            if line.startswith("diff --git"):
                parts = line.split(" ")
                if len(parts) >= 3:
                    # path like a/path b/path
                    file_b = parts[3]
                    if file_b.startswith("b/"):
                        file_b = file_b[2:]
                    current_file = file_b
                    stats[current_file] = {"insertions": 0, "deletions": 0}
            elif current_file and line.startswith("+++"):
                # ignore header lines
                continue
            elif current_file and line.startswith("---"):
                continue
            elif current_file:
                if line.startswith("+") and not line.startswith("+++"):
                    stats[current_file]["insertions"] += 1
                elif line.startswith("-") and not line.startswith("---"):
                    stats[current_file]["deletions"] += 1

        return [DiffStatEntry(path=path, insertions=s["insertions"], deletions=s["deletions"]) for path, s in stats.items()]
