import logging
import time
from typing import Dict, List, Any, Optional

import anyio
from anyio.streams.memory import MemoryObjectSendStream

from llm.utils import AsyncLLM, get_llm_client
from llm.common import Message, TextRaw, ToolUse, ToolResult, ToolUseResult
from api.fsm_tools import FSMToolProcessor, run_with_claude
from uuid import uuid4

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    ConversationMessage,
    AgentStatus,
    MessageKind,
)
from api.agent_server.interface import AgentInterface

logger = logging.getLogger(__name__)


class AsyncAgentSession(AgentInterface):
    def __init__(self, chatbot_id: str | None= None, trace_id: str | None = None, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""
        self.chatbot_id = chatbot_id or uuid4().hex
        self.trace_id = trace_id or uuid4().hex
        self.settings = settings or {}
        self.is_running = False
        self.is_complete = False
        self.fsm_instance = None
        self.processor_instance: FSMToolProcessor = FSMToolProcessor()
        self.messages = []
        self.llm_client: AsyncLLM = get_llm_client()

    async def initialize_fsm(self, messages: List[ConversationMessage], agent_state: Optional[Dict[str, Any]] = None):
        """Initialize the FSM with messages and optional state"""
        logger.info(f"Initializing FSM for trace {self.trace_id}")
        logger.debug(f"Agent state present: {agent_state is not None}")

        # Extract user messages from the conversation history
        user_messages = [msg.content for msg in messages if hasattr(msg, "role") and msg.role == "user"]
        app_description = "\n".join(user_messages)
        logger.debug(f"App description length: {len(app_description)}")
        # Create a proper Message object for the llm client
        self.messages = [Message(role="user", content=[TextRaw(app_description)])]
        return

    def get_state(self) -> Dict[str, Any]:
        """Get the current FSM state"""
        try:
            logger.debug(f"Getting state for trace {self.trace_id}")
            if not self.processor_instance.fsm_app:
                return {}

            fsm_app = self.processor_instance.fsm_app
            # Build state representation
            state_data = {
                "state": fsm_app.get_state(),
                "context": fsm_app.get_context().dump() if hasattr(fsm_app.get_context(), "dump") else {}
            }

            # Add available actions if the method exists in FSMToolProcessor
            if hasattr(self.processor_instance, "_get_available_actions"):
                state_data["actions"] = self.processor_instance._get_available_actions()

            return state_data
        except Exception as e:
            logger.error(f"Error getting state for trace {self.trace_id}: {str(e)}")
            return {}

    @property
    def user_answered(self) -> bool:
        if not self.messages:
              return False
        return self.messages[-1].role == "user"

    def bake_app_diff(self, app_out: Dict[str, Any]) -> None:
        logger.warning(f"No baking at the moment 🥖")

    async def process_step(self) -> Optional[AgentSseEvent]:
        """Process a single step and return an SSE event"""
        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return None

        try:
            logger.info(f"Processing step for trace {self.trace_id}")
            new_messages, is_complete, final_tool_result = await run_with_claude(self.processor_instance, self.llm_client, self.messages)
            self.is_complete = is_complete
            if final_tool_result or new_messages:
                status = AgentStatus.IDLE if is_complete else AgentStatus.RUNNING

                if new_messages:
                    self.messages += new_messages

                app_diff = None
                if final_tool_result and hasattr(final_tool_result, 'data') and 'application_out' in final_tool_result.data:
                    logger.info(f"Final tool result for trace {self.trace_id}: {final_tool_result}")
                    app_diff = self.bake_app_diff(final_tool_result.data["application_out"])
                    logger.info(f"App diff for trace {self.trace_id}: {app_diff}")

                # maybe we need to have 2 different messages instead: on message and on complete
                content = ""
                if new_messages:
                    # For the latest message, find the TextRaw content
                    last_message = new_messages[-1]
                    for item in last_message.content:
                        if isinstance(item, TextRaw):
                            content = item.text
                            break
                elif final_tool_result:
                    content = final_tool_result.content

                return AgentSseEvent(
                    status=status,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        role="agent",
                        kind=MessageKind.STAGE_RESULT,
                        content=content,
                        agent_state=self.get_state(),
                        unified_diff=app_diff
                    )
                )

            logger.info(f"No new message generated for trace {self.trace_id}")
            return None

        except Exception as e:
            logger.exception(f"Error in process_step: {str(e)}")

            self.is_complete = True
            return AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing step: {str(e)}",
                    agent_state=None,
                    unified_diff=None
                )
            )

    async def advance_fsm(self) -> bool:
        """
        Advance the FSM state. Returns True if more steps are needed,
        False if the FSM is complete or has reached a terminal state.
        """
        if self.is_complete:
            logger.info(f"FSM is already complete for trace {self.trace_id}")
            return False

        if self.processor_instance.work_in_progress.locked():
            logger.info(f"FSM is locked for trace {self.trace_id}, work in progress")
            return False

        if not self.user_answered:
             logger.info(f"User has not answered for trace {self.trace_id}")
             return False

        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return False

        logger.info(f"FSM should continue for trace {self.trace_id}")
        return True

    def cleanup(self):
        """Cleanup resources for this session"""
        logger.info(f"Cleaning up resources for trace {self.trace_id}")
        self.processor_instance = None
        self.messages = []
        logger.info(f"Resources cleaned up for trace {self.trace_id}")

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the incoming request and send events to the event stream.
        This is the main method required by the AgentInterface protocol.

        Args:
            request: Incoming agent request
            event_tx: Event transmission stream
        """
        try:
            logger.info(f"Processing request for {self.chatbot_id}:{self.trace_id}")

            # Initialize the FSM with the request data
            await self.initialize_fsm(request.all_messages, request.agent_state)

            # Process the initial step
            initial_event = await self.process_step()
            if initial_event:
                logger.info(f"Sending initial event for trace {self.trace_id}")
                await event_tx.send(initial_event)

            # Process subsequent steps until completion
            while True:
                should_continue = await self.advance_fsm()
                if not should_continue:
                    logger.info(f"FSM complete, processing final step for trace {self.trace_id}")
                    final_event = await self.process_step()
                    if final_event:
                        logger.info(f"Sending final event for trace {self.trace_id}")
                        await event_tx.send(final_event)
                    break

                logger.info(f"Processing next step for trace {self.trace_id}")
                event = await self.process_step()

                if event:
                    logger.info(f"Sending event with status {event.status} for trace {self.trace_id}")
                    await event_tx.send(event)

                if event and event.status == AgentStatus.IDLE:
                    logger.info(f"Agent is idle, stopping event stream for trace {self.trace_id}")
                    break

                await anyio.sleep(0.1)

        except Exception as e:
            logger.exception(f"Error in process: {str(e)}")
            error_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing request: {str(e)}",
                    agent_state=None,
                    unified_diff=None
                )
            )
            await event_tx.send(error_event)
        finally:
            logger.info(f"Cleaning up session for trace {self.trace_id}")
            self.cleanup()
