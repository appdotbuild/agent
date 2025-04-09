import logging
from typing import Dict, Any, Optional
from llm.utils import get_llm_client, AsyncLLM

from trpc_agent.application import FSMEvent as FsmEvent, FSMState as FsmState, FSMApplication as Application

# Configure logging
logger = logging.getLogger(__name__)


class FSMManager:
    """Manager for an FSM instance with complete state handling and lifecycle management"""

    def __init__(self, client: AsyncLLM | None = None):
        """
        Initialize the FSM manager with optional dependencies

        Args:
            client: AnthropicClient instance (created if not provided)
            compiler: Compiler instance (created if not provided)
            langfuse_client: Langfuse client (created if not provided)
        """
        self.client = client or get_llm_client()
        self.fsm_instance = None
        self.trace_id = None
        self.app_instance = None

    def get_full_external_state(self) -> Dict[str, Any]:
        """
        Get the full external state of the FSM for the external API
        """
        return {
            "state": self._get_current_state(),
            "context": self.fsm_instance.context,
            "actions": self._get_available_actions()
        }


    async def set_full_external_state(self, state: Dict[str, Any]):
        """
        Set full external state from external API
        Theoretically, this should be the same as the internal state
        But in case of blue-green deployment, the external state might be different from the internal state
        So here we may need to try to restore from previous schema
        """
        if not self.app_instance:
            logger.error("No active FSM application to set state")
            return

        # Create a new application from the checkpoint
        self.app_instance = await Application.from_checkpoint(state)


    def _get_current_state(self) -> FsmState:
        return self.app_instance.get_state()


    async def start_fsm(self, user_input: str) -> Dict[str, Any]:
        """
        Starts FSM in interactive mode and returns initial state output

        Args:
            user_input: User's description of the application

        Returns:
            Dict containing current_state, output, and available_actions
        """
        logger.info(f"Starting new FSM session with user input: {user_input[:100]}...")

        # Create FSM application from prompt
        self.app_instance = await Application.from_prompt(user_input)
        logger.debug("Created Application instance from prompt")

        # Store the reference to the internal state machine
        self.fsm_instance = self.app_instance.fsm

        # Start FSM
        logger.info("Starting FSM")
        try:
            await self.app_instance.start(client_callback=None)
            logger.info("FSM session started")
        except Exception as e:
            logger.exception(f"Error during FSM event processing: {str(e)}")
            return {"error": f"FSM initialization failed: {str(e)}"}

        # Check if FSM entered FAILURE state immediately
        current_state = self.app_instance.get_state()
        if current_state == FsmState.FAILURE:
            error_msg = self.app_instance.get_context().error or "Unknown error"
            logger.error(f"FSM entered FAILURE state during initialization: {error_msg}")
            return {
                "error": f"FSM initialization failed: {error_msg}",
                "current_state": current_state
            }

        output = self._get_state_output()
        available_actions = self._get_available_actions()
        logger.debug(f"Available actions: {available_actions}")

        # Add the current state to the output
        return {
            "current_state": current_state,
            "output": output,
            "available_actions": available_actions
        }

    async def confirm_state(self) -> Dict[str, Any]:
        """
        Accept current output and advance to next state

        Returns:
            Dict containing new_state, output, and available_actions
        """
        if not self.app_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        # Log the current state before confirmation
        previous_state = self._get_current_state()
        logger.info(f"Current state before confirmation: {previous_state}")

        # Confirm the current state
        logger.info("Sending CONFIRM event to FSM")
        try:
            await self.app_instance.send_event(FsmEvent("CONFIRM"))
        except Exception as e:
            logger.exception(f"Error during FSM confirm event processing")
            return {"error": f"FSM confirmation failed: {str(e)}"}

        # Prepare response
        current_state = self._get_current_state()
        logger.info(f"State after confirmation: {current_state}")

        # Check if FSM entered FAILURE state
        if current_state == FsmState.FAILURE:
            error_msg = self.app_instance.get_context().error or "Unknown error"
            logger.error(f"FSM entered FAILURE state during confirmation: {error_msg}")
            return {
                "error": f"FSM confirmation failed: {error_msg}",
                "current_state": current_state
            }

        output = self._get_state_output()
        available_actions = self._get_available_actions()
        logger.debug(f"Available actions after confirmation: {available_actions}")

        return {
            "current_state": current_state,
            "output": output,
            "available_actions": available_actions
        }

    async def provide_feedback(self, feedback: str, component_name: str = None) -> Dict[str, Any]:
        """
        Submit feedback and trigger revision

        Args:
            feedback: Feedback to provide
            component_name: Optional component name for handler-specific feedback

        Returns:
            Dict containing current_state, revised_output, and available_actions
        """
        if not self.app_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        # Determine current state and event type
        current_state = self._get_current_state()
        event_type = self._get_revision_event_type(current_state)
        logger.info(f"Current state: {current_state}, Revision event type: {event_type}")

        if not event_type:
            logger.error(f"Cannot provide feedback for state {current_state}")
            return {"error": f"Cannot provide feedback for state {current_state}"}

        # Handle handler-specific feedback vs standard feedback
        try:
            match current_state:
                case FsmState.REVIEW_HANDLERS:
                    if not component_name:
                        logger.error(f"Component name required for {current_state}")
                        return {"error": f"Component name required for {current_state}"}
                    # Create a dict with the specific handler feedback
                    logger.info(f"Providing handler-specific feedback for component: {component_name}")
                    await self.app_instance.send_event(FsmEvent(event_type), feedback)
                case _:
                    # Send standard feedback
                    logger.info("Providing standard feedback")
                    await self.app_instance.send_event(FsmEvent(event_type), feedback)

            logger.info("Feedback successfully sent to FSM")
        except Exception as e:
            logger.exception(f"Error while sending feedback")
            return {"error": f"Error while processing feedback: {str(e)}"}

        # Prepare response
        new_state = self._get_current_state()
        logger.info(f"State after feedback: {new_state}")

        # Check if we entered FAILURE state which requires special handling
        if new_state == FsmState.FAILURE:
            # Extract error information
            error_msg = self.app_instance.get_context().error or "Unknown error"

            # Log the detailed error
            logger.error(f"FSM entered FAILURE state during feedback processing: {error_msg}")

            # Return error information with the state
            return {
                "current_state": new_state,
                "error": error_msg,
                "available_actions": self._get_available_actions()
            }

        output = self._get_state_output()
        available_actions = self._get_available_actions()
        logger.debug(f"Available actions after feedback: {available_actions}")

        return {
            "current_state": new_state,
            "output": output,
            "available_actions": available_actions
        }

    async def complete_fsm(self) -> Dict[str, Any]:
        """
        Finalize and return all generated artifacts

        Returns:
            Dict containing all final outputs and status
        """
        if not self.app_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        current_state = self._get_current_state()
        if "review" in str(current_state).lower():
            # send a single confirm event to move to next state
            await self.app_instance.send_event(FsmEvent("CONFIRM"))
            current_state = self._get_current_state()

        # Check if FSM completed but with empty outputs (likely a silent failure)
        context = self.app_instance.get_context()
        if current_state == FsmState.COMPLETE and not context.server_files and not context.frontend_files:
            error_msg = "FSM completed but didn't generate any artifacts. This indicates a failure in the generation process."
            logger.error(error_msg)
            return {"error": error_msg, "status": "failed", "current_state": current_state}

        # Get all outputs
        logger.info("Getting outputs from FSM application context")
        context = self.app_instance.get_context()
        result = {}

        try:
            match current_state:
                case FsmState.COMPLETE:
                    # Include all artifacts
                    logger.info("FSM completed successfully, gathering artifacts")
                    result = {
                        "server_files": context.server_files or {},
                        "frontend_files": context.frontend_files or {}
                    }

                case FsmState.FAILURE:
                    # Include error information
                    error_msg = context.error or "Unknown error"
                    logger.error(f"FSM failed with error: {error_msg}")
                    # Add detailed error information to the result
                    result["error"] = error_msg
        except Exception as e:
            logger.exception(f"Error collecting outputs: {str(e)}")
            result["extraction_error"] = str(e)

        status = "complete" if current_state == FsmState.COMPLETE else "failed"
        logger.info(f"FSM completed with status: {status}")

        return {
            "status": status,
            "final_outputs": result
        }

    def is_active(self) -> bool:
        """Check if there's an active FSM session"""
        return self.app_instance is not None

    # Helper methods

    def _get_revision_event_type(self, state: str) -> Optional[str]:
        """Map review state to corresponding revision event type"""
        logger.debug(f"Getting revision event type for state: {state}")
        event_map = {
            FsmState.REVIEW_DRAFT: "FEEDBACK_DRAFT",
            FsmState.REVIEW_HANDLERS: "FEEDBACK_HANDLERS",
            FsmState.REVIEW_INDEX: "FEEDBACK_INDEX",
            FsmState.REVIEW_FRONTEND: "FEEDBACK_FRONTEND"
        }
        result = event_map.get(state)
        if result:
            logger.debug(f"Found revision event type: {result}")
        else:
            logger.debug(f"No revision event type found for state: {state}")
        return result

    def _get_available_actions(self) -> Dict[str, str]:
        """Get available actions for current state"""
        current_state = self._get_current_state()
        logger.debug(f"Getting available actions for state: {current_state}")

        actions = {}
        match current_state:
            case FsmState.REVIEW_DRAFT | FsmState.REVIEW_HANDLERS | FsmState.REVIEW_INDEX | FsmState.REVIEW_FRONTEND:
                actions = {
                    "confirm": "Accept current output and continue",
                    "revise": "Provide feedback and revise"
                }
                logger.debug(f"Review state detected: {current_state}, offering confirm/revise actions")
            case FsmState.COMPLETE:
                actions = {"complete": "Finalize and get all artifacts"}
                logger.debug("FSM is in COMPLETE state, offering complete action")
            case FsmState.FAILURE:
                actions = {"get_error": "Get error details"}
                logger.debug("FSM is in FAILURE state, offering get_error action")
            case _:
                actions = {"wait": "Wait for processing to complete"}
                logger.debug(f"FSM is in processing state: {current_state}, offering wait action")

        return actions

    def _get_state_output(self) -> Dict[str, Any]:
        """Extract relevant output for the current state"""
        current_state = self._get_current_state()
        logger.debug(f"Getting output for state: {current_state}")

        if not self.app_instance:
            return {"status": "error", "message": "No active FSM session"}

        context = self.app_instance.get_context()

        try:
            match current_state:
                case FsmState.REVIEW_DRAFT:
                    return {
                        "draft": context.draft
                    }

                case FsmState.REVIEW_HANDLERS:
                    if context.server_files:
                        handler_files = {}
                        for filename, content in context.server_files.items():
                            if '/handlers/' in filename:
                                handler_files[filename] = content
                        return {"handlers": handler_files}
                    return {"status": "handlers_not_found"}

                case FsmState.REVIEW_INDEX:
                    if context.server_files:
                        index_files = {}
                        for filename, content in context.server_files.items():
                            if 'index.ts' in filename:
                                index_files[filename] = content
                        return {"index": index_files}
                    return {"status": "index_not_found"}

                case FsmState.REVIEW_FRONTEND:
                    return {"frontend": context.frontend_files}

                case FsmState.COMPLETE:
                    return {
                        "server_files": context.server_files,
                        "frontend_files": context.frontend_files
                    }

                case FsmState.FAILURE:
                    error_msg = context.error or "Unknown error"
                    logger.error(f"FSM failed with error: {error_msg}")
                    return {"error": error_msg}

                case _:
                    logger.debug(f"State {current_state} is a processing state, returning processing status")
                    return {"status": "processing"}
        except Exception as e:
            logger.exception(f"Error getting state output: {str(e)}")
            return {"status": "error", "message": f"Error retrieving state output: {str(e)}"}

        logger.debug("No specific output found for current state, returning processing status")
        return {"status": "processing"}
