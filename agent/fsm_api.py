import os
import uuid
import logging
from typing import Dict, Any, Optional
from dataclasses import asdict
from anthropic import AnthropicBedrock
from langfuse import Langfuse
from compiler.core import Compiler

# Configure logging
logger = logging.getLogger(__name__)

import application
from application import FsmEvent, FsmState, Application
from statemachine import StateMachine


class FSMManager:
    """Manager for a single FSM instance with state handling"""
    
    def __init__(self):
        """Initialize an empty FSM manager"""
        self.fsm_instance = None
        self.trace_id = None
        self.app_instance = None
        
    def start_fsm(self, user_input: str) -> Dict[str, Any]:
        """
        Starts FSM in interactive mode and returns initial state output

        Args:
            user_input: User's description of the application

        Returns:
            Dict containing current_state, output, and available_actions
        """
        logger.info(f"Starting new FSM session with user input: {user_input[:100]}...")

        # Initialize clients and services
        langfuse_client = Langfuse()
        self.trace_id = uuid.uuid4().hex
        trace = langfuse_client.trace(
            id=self.trace_id,
            name="agent_controlled_fsm",
            user_id=os.environ.get("USER_ID", "agent_user"),
            metadata={"agent_controlled": True},
        )
        logger.debug(f"Created Langfuse trace with ID: {self.trace_id}")

        aws_client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
        compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        logger.debug("Initialized AWS client and compiler")

        # Create application with interactive mode enabled
        self.app_instance = Application(
            client=aws_client,
            compiler=compiler,
            langfuse_client=langfuse_client,
            interactive_mode=True
        )
        logger.debug("Created Application instance with interactive_mode=True")

        # Initialize FSM context with user input
        fsm_context: application.FSMContext = {
            "user_requests": [user_input]
        }

        logger.debug("Creating FSM states...")
        fsm_states = self.app_instance.make_fsm_states(trace_id=trace.id, observation_id=trace.id)
        logger.debug(f"Created {len(fsm_states)} FSM states")

        logger.debug("Initializing StateMachine...")
        self.fsm_instance = StateMachine[application.FSMContext](fsm_states, fsm_context)

        # Start FSM
        logger.info("Sending initial PROMPT event to FSM")
        try:
            self.fsm_instance.send(FsmEvent(type_="PROMPT"))
            logger.info("FSM session started")
        except Exception as e:
            logger.error(f"Error during FSM event processing: {str(e)}")
            return {"error": f"FSM initialization failed: {str(e)}"}
        
        # Check if FSM entered FAILURE state immediately
        current_state = self.fsm_instance.stack_path[-1]
        if current_state == FsmState.FAILURE:
            error_msg = self.fsm_instance.context.get("error", "Unknown error")
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

    def confirm_state(self) -> Dict[str, Any]:
        """
        Accept current output and advance to next state

        Returns:
            Dict containing new_state, output, and available_actions
        """
        if not self.fsm_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        # Log the current state before confirmation
        previous_state = self.fsm_instance.stack_path[-1]
        logger.info(f"Current state before confirmation: {previous_state}")

        # Confirm the current state
        logger.info("Sending CONFIRM event to FSM")
        try:
            self.fsm_instance.send(FsmEvent(type_="CONFIRM"))
        except Exception as e:
            logger.error(f"Error during FSM confirm event processing: {str(e)}")
            return {"error": f"FSM confirmation failed: {str(e)}"}

        # Prepare response
        current_state = self.fsm_instance.stack_path[-1]
        logger.info(f"State after confirmation: {current_state}")
        
        # Check if FSM entered FAILURE state
        if current_state == FsmState.FAILURE:
            error_msg = self.fsm_instance.context.get("error", "Unknown error")
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

    def provide_feedback(self, feedback: str, component_name: str = None) -> Dict[str, Any]:
        """
        Submit feedback and trigger revision

        Args:
            feedback: Feedback to provide
            component_name: Optional component name for handler-specific feedback

        Returns:
            Dict containing current_state, revised_output, and available_actions
        """
        if not self.fsm_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        # Determine current state and event type
        current_state = self.fsm_instance.stack_path[-1]
        event_type = self._get_revision_event_type(current_state)
        logger.info(f"Current state: {current_state}, Revision event type: {event_type}")

        if not event_type:
            logger.error(f"Cannot provide feedback for state {current_state}")
            return {"error": f"Cannot provide feedback for state {current_state}"}

        # Handle handler-specific feedback vs standard feedback
        try:
            match current_state:
                case FsmState.HANDLER_TESTS_REVIEW | FsmState.HANDLERS_REVIEW:
                    if not component_name:
                        logger.error(f"Component name required for {current_state}")
                        return {"error": f"Component name required for {current_state}"}
                    # Create a dict with the specific handler feedback
                    logger.info(f"Providing handler-specific feedback for component: {component_name}")
                    feedback_dict = {component_name: feedback}
                    logger.debug(f"Sending event {event_type} with feedback dict")
                    self.fsm_instance.send(FsmEvent(event_type, feedback_dict))
                case _:
                    # Send standard feedback
                    logger.info("Providing standard feedback")
                    logger.debug(f"Sending event {event_type} with feedback string")
                    self.fsm_instance.send(FsmEvent(event_type, feedback))

            logger.info("Feedback successfully sent to FSM")
        except Exception as e:
            logger.error(f"Error while sending feedback: {str(e)}")
            return {"error": f"Error while processing feedback: {str(e)}"}

        # Prepare response
        new_state = self.fsm_instance.stack_path[-1]
        logger.info(f"State after feedback: {new_state}")

        # Check if we entered FAILURE state which requires special handling
        if new_state == FsmState.FAILURE:
            # Extract error information from context
            error_context = self.fsm_instance.context.get("error", "Unknown error")
            error_msg = str(error_context) if error_context else "FSM entered FAILURE state"
            
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

    def complete_fsm(self) -> Dict[str, Any]:
        """
        Finalize and return all generated artifacts

        Returns:
            Dict containing all final outputs and status
        """
        if not self.fsm_instance:
            logger.error("No active FSM session")
            return {"error": "No active FSM session"}

        # Check if FSM is in COMPLETE or FAILURE state
        current_state = self.fsm_instance.stack_path[-1]
        logger.info(f"Current state for completion: {current_state}")

        if current_state not in [FsmState.COMPLETE, FsmState.FAILURE]:
            logger.error(f"FSM is not in a completion state. Current state: {current_state}")
            return {"error": f"FSM is not complete. Current state: {current_state}"}
            
        # Check if FSM completed but with empty outputs (likely a silent failure)
        context = self.fsm_instance.context
        if current_state == FsmState.COMPLETE and not any(key in context for key in 
                                                     ["typespec_schema", "drizzle_schema", "typescript_schema", 
                                                      "handler_tests", "handlers"]):
            error_msg = "FSM completed but didn't generate any artifacts. This indicates a failure in the generation process."
            logger.error(error_msg)
            return {"error": error_msg, "status": "failed", "current_state": current_state}

        # Collect all outputs
        logger.info("Collecting outputs from FSM context")
        context = self.fsm_instance.context
        result = {}

        try:
            match current_state:
                case FsmState.COMPLETE:
                    # Include all artifacts
                    logger.info("FSM completed successfully, gathering artifacts")

                    if "typespec_schema" in context:
                        logger.debug("Adding TypeSpec schema to results")
                        result["typespec"] = {
                            "reasoning": context["typespec_schema"].reasoning,
                            "typespec": context["typespec_schema"].typespec,
                            "llm_functions": context["typespec_schema"].llm_functions
                        }

                    if "drizzle_schema" in context:
                        logger.debug("Adding Drizzle schema to results")
                        result["drizzle"] = {
                            "reasoning": context["drizzle_schema"].reasoning,
                            "drizzle_schema": context["drizzle_schema"].drizzle_schema
                        }

                    if "typescript_schema" in context:
                        logger.debug("Adding TypeScript schema to results")
                        try:
                            # Check if functions is a valid attribute and iterable
                            if not hasattr(context["typescript_schema"], "functions"):
                                logger.error("typescript_schema has no 'functions' attribute")
                                result["typescript"] = {
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "functions_error": "typescript_schema object has no 'functions' attribute"
                                }
                            elif context["typescript_schema"].functions is None:
                                logger.error("typescript_schema.functions is None")
                                result["typescript"] = {
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "functions_error": "typescript_schema.functions is None"
                                }
                            else:
                                # Debug the functions structure
                                functions = context["typescript_schema"].functions
                                logger.debug(f"Functions type: {type(functions)}")
                                logger.debug(f"Functions content: {functions}")

                                # Process the functions safely
                                processed_functions = []
                                for i, f in enumerate(functions):
                                    logger.debug(f"Processing function {i}: {type(f)}")
                                    try:
                                        processed_functions.append(asdict(f))
                                    except Exception as e:
                                        logger.error(f"Error converting function {i} to dict: {str(e)}")
                                        # Add as much info as we can extract
                                        func_info = {"error": str(e)}
                                        for attr in ["name", "argument_type", "argument_schema", "return_type"]:
                                            if hasattr(f, attr):
                                                func_info[attr] = getattr(f, attr)
                                        processed_functions.append(func_info)

                                result["typescript"] = {
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "functions": processed_functions
                                }
                                logger.debug(f"Successfully processed {len(processed_functions)} TypeScript functions")
                        except Exception as e:
                            logger.error(f"Error processing TypeScript functions: {str(e)}")
                            result["typescript"] = {
                                "reasoning": context["typescript_schema"].reasoning,
                                "typescript_schema": context["typescript_schema"].typescript_schema,
                                "functions_error": f"Error processing functions: {str(e)}"
                            }

                    if "handler_tests" in context:
                        logger.debug("Adding handler tests to results")
                        result["handler_tests"] = {
                            name: {"source": test.source}
                            for name, test in context["handler_tests"].items()
                        }
                        logger.debug(f"Added {len(context['handler_tests'])} handler tests")

                    if "handlers" in context:
                        logger.debug("Adding handlers to results")
                        result["handlers"] = {
                            name: {"source": handler.source if hasattr(handler, "source") else str(handler)}
                            for name, handler in context["handlers"].items()
                        }
                        logger.debug(f"Added {len(context['handlers'])} handlers")

                case FsmState.FAILURE:
                    # Include error information
                    error_msg = str(context.get("error", "Unknown error"))
                    logger.error(f"FSM failed with error: {error_msg}")
                    # Add detailed error information to the result
                    result["error"] = error_msg
                    # Also include the most recent state transition info if available
                    if "last_transition" in context:
                        result["last_transition"] = context["last_transition"]
        except Exception as e:
            logger.error(f"Error collecting outputs: {str(e)}")
            result["extraction_error"] = str(e)

        # Reset state
        logger.info("Resetting FSM session")
        self.fsm_instance = None
        self.trace_id = None
        self.app_instance = None

        status = "complete" if current_state == FsmState.COMPLETE else "failed"
        logger.info(f"FSM completed with status: {status}")

        return {
            "status": status,
            "final_outputs": result
        }

    def is_active(self) -> bool:
        """Check if there's an active FSM session"""
        return self.fsm_instance is not None

    # Helper methods
    
    def _get_revision_event_type(self, state: str) -> Optional[str]:
        """Map review state to corresponding revision event type"""
        logger.debug(f"Getting revision event type for state: {state}")
        event_map = {
            FsmState.TYPESPEC_REVIEW: FsmEvent.REVISE_TYPESPEC,
            FsmState.DRIZZLE_REVIEW: FsmEvent.REVISE_DRIZZLE,
            FsmState.TYPESCRIPT_REVIEW: FsmEvent.REVISE_TYPESCRIPT,
            FsmState.HANDLER_TESTS_REVIEW: FsmEvent.REVISE_HANDLER_TESTS,
            FsmState.HANDLERS_REVIEW: FsmEvent.REVISE_HANDLERS
        }
        result = event_map.get(state)
        if result:
            logger.debug(f"Found revision event type: {result}")
        else:
            logger.debug(f"No revision event type found for state: {state}")
        return result

    def _get_available_actions(self) -> Dict[str, str]:
        """Get available actions for current state"""
        current_state = self.fsm_instance.stack_path[-1]
        logger.debug(f"Getting available actions for state: {current_state}")

        actions = {}
        match current_state:
            case FsmState.TYPESPEC_REVIEW | FsmState.DRIZZLE_REVIEW | FsmState.TYPESCRIPT_REVIEW | \
                 FsmState.HANDLER_TESTS_REVIEW | FsmState.HANDLERS_REVIEW:
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
        current_state = self.fsm_instance.stack_path[-1]
        logger.debug(f"Getting output for state: {current_state}")
        context = self.fsm_instance.context

        try:
            match current_state:
                case FsmState.TYPESPEC_REVIEW:
                    if "typespec_schema" in context:
                        logger.debug("Found TypeSpec schema in context")
                        return {
                            "typespec": context["typespec_schema"].typespec,
                            "reasoning": context["typespec_schema"].reasoning
                        }
                    else:
                        logger.warning("TypeSpec schema not found in context for TYPESPEC_REVIEW state")

                case FsmState.DRIZZLE_REVIEW:
                    if "drizzle_schema" in context:
                        logger.debug("Found Drizzle schema in context")
                        return {
                            "drizzle_schema": context["drizzle_schema"].drizzle_schema,
                            "reasoning": context["drizzle_schema"].reasoning
                        }
                    else:
                        logger.warning("Drizzle schema not found in context for DRIZZLE_REVIEW state")

                case FsmState.TYPESCRIPT_REVIEW:
                    if "typescript_schema" in context:
                        logger.debug("Found TypeScript schema in context")
                        try:
                            # Check if functions is a valid attribute and iterable
                            if not hasattr(context["typescript_schema"], "functions"):
                                logger.error("typescript_schema has no 'functions' attribute")
                                return {
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "functions_error": "typescript_schema object has no 'functions' attribute"
                                }
                            elif context["typescript_schema"].functions is None:
                                logger.error("typescript_schema.functions is None")
                                return {
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "functions_error": "typescript_schema.functions is None"
                                }
                            else:
                                # Debug the functions structure
                                functions = context["typescript_schema"].functions
                                logger.debug(f"Functions type: {type(functions)}")
                                logger.debug(f"Functions content: {functions}")

                                # Process the functions safely
                                processed_functions = []
                                for i, f in enumerate(functions):
                                    logger.debug(f"Processing function {i}: {type(f)}")
                                    try:
                                        processed_functions.append(asdict(f))
                                    except Exception as e:
                                        logger.error(f"Error converting function {i} to dict: {str(e)}")
                                        # Add as much info as we can extract
                                        func_info = {"error": str(e)}
                                        for attr in ["name", "argument_type", "argument_schema", "return_type"]:
                                            if hasattr(f, attr):
                                                func_info[attr] = getattr(f, attr)
                                        processed_functions.append(func_info)

                                result = {
                                    "typescript_schema": context["typescript_schema"].typescript_schema,
                                    "reasoning": context["typescript_schema"].reasoning,
                                    "functions": processed_functions
                                }
                                logger.debug(f"Successfully processed {len(processed_functions)} TypeScript functions")
                                return result
                        except Exception as e:
                            logger.error(f"Error processing TypeScript functions: {str(e)}")
                            return {
                                "typescript_schema": context["typescript_schema"].typescript_schema,
                                "reasoning": context["typescript_schema"].reasoning,
                                "functions_error": f"Error processing functions: {str(e)}"
                            }
                    else:
                        logger.warning("TypeScript schema not found in context for TYPESCRIPT_REVIEW state")

                case FsmState.HANDLER_TESTS_REVIEW:
                    if "handler_tests" in context:
                        logger.debug(f"Found {len(context['handler_tests'])} handler tests in context")
                        return {
                            "handler_tests": {
                                name: {"source": test.source}
                                for name, test in context["handler_tests"].items()
                            }
                        }
                    else:
                        logger.warning("Handler tests not found in context for HANDLER_TESTS_REVIEW state")

                case FsmState.HANDLERS_REVIEW:
                    if "handlers" in context:
                        logger.debug(f"Found {len(context['handlers'])} handlers in context")
                        return {
                            "handlers": {
                                name: {"source": handler.source if hasattr(handler, "source") else str(handler)}
                                for name, handler in context["handlers"].items()
                            }
                        }
                    else:
                        logger.warning("Handlers not found in context for HANDLERS_REVIEW state")

                case FsmState.COMPLETE:
                    # Return all generated artifacts
                    logger.debug("Compiling all artifacts for COMPLETE state")
                    result = {}

                    if "typespec_schema" in context:
                        logger.debug("Adding TypeSpec schema to complete result")
                        result["typespec"] = {
                            "typespec": context["typespec_schema"].typespec,
                            "reasoning": context["typespec_schema"].reasoning
                        }

                    if "drizzle_schema" in context:
                        logger.debug("Adding Drizzle schema to complete result")
                        result["drizzle"] = {
                            "drizzle_schema": context["drizzle_schema"].drizzle_schema,
                            "reasoning": context["drizzle_schema"].reasoning
                        }

                    if "typescript_schema" in context:
                        logger.debug("Adding TypeScript schema to complete result")
                        result["typescript"] = {
                            "typescript_schema": context["typescript_schema"].typescript_schema,
                            "reasoning": context["typescript_schema"].reasoning
                        }

                    if "handler_tests" in context:
                        logger.debug(f"Adding {len(context['handler_tests'])} handler tests to complete result")
                        result["handler_tests"] = {
                            name: {"source": test.source}
                            for name, test in context["handler_tests"].items()
                        }

                    if "handlers" in context:
                        logger.debug(f"Adding {len(context['handlers'])} handlers to complete result")
                        result["handlers"] = {
                            name: {"source": handler.source if hasattr(handler, "source") else str(handler)}
                            for name, handler in context["handlers"].items()
                        }

                    logger.debug(f"Complete result contains {len(result)} artifact categories")
                    return result

                case FsmState.FAILURE:
                    if "error" in context:
                        error_msg = str(context["error"])
                        logger.error(f"FSM failed with error: {error_msg}")
                        result = {"error": error_msg}
                        
                        # Include additional error context if available
                        if "failed_actor" in context:
                            result["failed_actor"] = context["failed_actor"]
                            logger.error(f"Failed actor: {context['failed_actor']}")
                            
                        return result
                    else:
                        logger.error("FSM in FAILURE state but no error found in context")
                        return {"error": "Unknown error"}

                case _:
                    logger.debug(f"State {current_state} is a processing state, returning processing status")
                    return {"status": "processing"}
        except Exception as e:
            logger.error(f"Error getting state output: {str(e)}")
            return {"status": "error", "message": f"Error retrieving state output: {str(e)}"}

        logger.debug("No specific output found for current state, returning processing status")
        return {"status": "processing"}


# Create a singleton instance for easy import
fsm_manager = FSMManager()

# Convenience functions that use the singleton
def start_fsm(user_input: str) -> Dict[str, Any]:
    """Start a new FSM session with the provided user input"""
    return fsm_manager.start_fsm(user_input)

def confirm_state() -> Dict[str, Any]:
    """Confirm the current state and advance to the next state"""
    return fsm_manager.confirm_state()

def provide_feedback(feedback: str, component_name: str = None) -> Dict[str, Any]:
    """Provide feedback for the current state"""
    return fsm_manager.provide_feedback(feedback, component_name)

def complete_fsm() -> Dict[str, Any]:
    """Complete the FSM session and return all artifacts"""
    return fsm_manager.complete_fsm()

def is_active() -> bool:
    """Check if there's an active FSM session"""
    return fsm_manager.is_active()