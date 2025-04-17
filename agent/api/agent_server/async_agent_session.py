import logging
from typing import Dict, List, Any, Optional

import anyio
from anyio.streams.memory import MemoryObjectSendStream

from llm.utils import AsyncLLM, get_llm_client
from llm.common import Message, TextRaw
from api.fsm_tools import FSMToolProcessor
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
import warnings


logger = logging.getLogger(__name__)



class AsyncAgentSession(AgentInterface):
    def __init__(self, application_id: str | None= None, trace_id: str | None = None, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""

        warnings.warn("This is deprecated, annoy Igor to remove it", DeprecationWarning)
        self.application_id = application_id or uuid4().hex
        self.trace_id = trace_id or uuid4().hex
        self.settings = settings or {}
        self.is_running = False
        self.is_complete = False
        self.fsm_instance = None
        self.processor_instance: FSMToolProcessor | None = None
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
        
        # Initialize processor_instance if not already initialized
        from trpc_agent.application import FSMApplication
        
        if agent_state:
            logger.info(f"Loading FSM state for trace {self.trace_id}")
            fsm = await FSMApplication.load(agent_state["fsm_state"])
            self.processor_instance = FSMToolProcessor(FSMApplication, fsm, settings=self.settings)
        else:
            logger.info(f"Creating new FSM instance for trace {self.trace_id}")
            self.processor_instance = FSMToolProcessor(FSMApplication, settings=self.settings)
        
        return

    def get_state(self) -> Dict[str, Any]:
        """Get the current FSM state"""
        try:
            logger.debug(f"Getting state for trace {self.trace_id}")
            if not self.processor_instance:
                logger.warning(f"No processor instance found for trace {self.trace_id}")
                return {}
                
            if not hasattr(self.processor_instance, "fsm_app") or not self.processor_instance.fsm_app:
                logger.warning(f"No FSM app found for trace {self.trace_id}")
                return {}

            if hasattr(self.processor_instance, "fsm_as_result"):
                try:
                    result = self.processor_instance.fsm_as_result()
                    return result
                except Exception as e:
                    logger.error(f"Error getting FSM result: {str(e)}")
                    return {}
            
            fsm_app = self.processor_instance.fsm_app
            state_data = {
                "current_state": fsm_app.current_state if hasattr(fsm_app, "current_state") else "",
                "output": fsm_app.state_output if hasattr(fsm_app, "state_output") else {},
                "available_actions": fsm_app.available_actions if hasattr(fsm_app, "available_actions") else {}
            }
            
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
        logger.warning("No baking at the moment 🥖")

    async def process_step(self) -> Optional[AgentSseEvent]:
        """Process a single step and return an SSE event"""
        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return None

        try:
            logger.info(f"Processing step for trace {self.trace_id}")
            try:
                if "max_tokens" not in self.settings:
                    logger.debug(f"Setting default max_tokens for trace {self.trace_id}")
                    self.settings["max_tokens"] = 4096
                new_messages = await self.processor_instance.step(self.messages, self.llm_client, self.settings)
            except Exception:
                logger.exception(f"Exception during processor_instance.step for trace {self.trace_id}")
                raise
                
            is_complete = self.processor_instance.fsm_app and self.processor_instance.fsm_app.is_completed
            final_tool_result = None
            self.is_complete = is_complete
            if final_tool_result or new_messages:
                if new_messages:
                    self.messages += new_messages

                status = AgentStatus.IDLE if (is_complete or not self.user_answered) else AgentStatus.RUNNING

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
                        agentState=self.get_state(),
                        unifiedDiff=app_diff
                    )
                )

            logger.info(f"No new message generated for trace {self.trace_id}")
            return None

        except Exception as e:
            logger.exception(f"Error in process_step (outer handler) for trace {self.trace_id}: {str(e)}")

            self.is_complete = True
            return AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing step: {str(e)}",
                    agentState=None,
                    unifiedDiff=None
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

        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return False

        # Check if work is in progress using the step method instead of directly accessing work_in_progress
        try:
            if hasattr(self.processor_instance, "fsm_app") and self.processor_instance.fsm_app:
                logger.info(f"FSM is in progress for trace {self.trace_id}")
                return False
        except Exception as e:
            logger.warning(f"Error checking FSM progress: {str(e)}")
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
            logger.info(f"Processing request for {self.application_id}:{self.trace_id}")

            # Check if we need to initialize or if this is a continuation with an existing state
            if request.agent_state:
                logger.info(f"Continuing with existing state for trace {self.trace_id}")
            else:
                logger.info(f"Initializing new session for trace {self.trace_id}")

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
                    logger.info(f"Stopping event stream for trace {self.trace_id}")
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
                    agentState=None,
                    unifiedDiff=None
                )
            )
            await event_tx.send(error_event)
        finally:
            if request.agent_state is None:
                # Only cleanup if this was a new session
                logger.info(f"Cleaning up new session for trace {self.trace_id}")
                self.cleanup()
            else:
                logger.info(f"Preserving state for continued session {self.trace_id}")
            await event_tx.aclose()
