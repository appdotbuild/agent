from dataclasses import dataclass
from typing import Optional, Any, Dict, Callable, List, Tuple, TypeVar, Generic, Type
import jinja2
import threading
from anthropic.types import MessageParam
from anthropic import AnthropicBedrock
import os
import uuid
from tracing_client import TracingClient
from compiler.core import Compiler
from fsm_core import drizzle
from fsm_core import typespec as tsp
from fsm_core import typescript as ts
from fsm_core import handlers
from fsm_core import handler_tests
from application import TypespecActor, DrizzleActor, TypescriptActor, HandlerTestsActor, HandlersActor
from langfuse import Langfuse
from langfuse.decorators import langfuse_context
import logging
import coloredlogs
from fire import Fire


coloredlogs.install(level="INFO")
logger = logging.getLogger(__name__)

@dataclass
class StepResult:
    """Result of a policy step with success flag and relevant data."""
    success: bool
    data: Any
    error: Optional[str] = None

    def to_dict(self):
        """Convert the result to a dictionary for serialization."""
        result = {
            "success": self.success,
            "error": self.error,
            "data": self.data
        }
        return {x: y for x, y in result.items() if y is not None}


class Context:
    """Thread-safe global context for storing state between operations."""
    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Context, cls).__new__(cls)
                cls._instance._storage = {}
            return cls._instance

    def set(self, key: str, value: Any):
        """Set a value in the context."""
        logger.info(f"[Context] Setting value for key: {key}")
        with self._lock:
            self._storage[key] = value

    def get(self, key: str, default=None) -> Any:
        """Get a value from the context."""
        with self._lock:
            return self._storage.get(key, default)

    def clear(self):
        """Clear all values in the context."""
        with self._lock:
            self._storage = {}

    def save_locally(self):
        with self._lock:
            out_dir = self._storage.get("output_dir")
            if not out_dir:
                raise ValueError("Output directory not set in context")

            tsp_dir = os.path.join(out_dir, "tsp_schema")
            os.makedirs(tsp_dir, exist_ok=True)
            with open(os.path.join(tsp_dir, "main.tsp"), "w") as f:
                # it will not work for real because we also need headers, but fine for PoC
                f.write(self._storage.get("last_typespec", ""))

            # Save TypeScript schema
            ts_dir = os.path.join(out_dir, "app_schema", "src", "common")
            os.makedirs(ts_dir, exist_ok=True)
            with open(os.path.join(ts_dir, "schema.ts"), "w") as f:
                f.write(self._storage.get("last_typescript", ""))

            # Save Drizzle schema
            drizzle_dir = os.path.join(out_dir, "app_schema", "src", "db", "schema")
            os.makedirs(drizzle_dir, exist_ok=True)
            with open(os.path.join(drizzle_dir, "application.ts"), "w") as f:
                f.write(self._storage.get("last_schema", ""))

    def load_locally(self):
        with self._lock:
            out_dir = self._storage.get("output_dir")
            if not out_dir:
                raise ValueError("Output directory not set in context")

            tsp_dir = os.path.join(out_dir, "tsp_schema")
            with open(os.path.join(tsp_dir, "main.tsp"), "r") as f:
                self._storage["last_typespec"] = f.read()

            # Load TypeScript schema
            ts_dir = os.path.join(out_dir, "app_schema", "src", "common")
            with open(os.path.join(ts_dir, "schema.ts"), "r") as f:
                self._storage["last_typescript"] = f.read()

            # Load Drizzle schema
            drizzle_dir = os.path.join(out_dir, "app_schema", "src", "db", "schema")
            with open(os.path.join(drizzle_dir, "application.ts"), "r") as f:
                self._storage["last_schema"] = f.read()


class Processor:
    """Base processor class that defines the interface for all processors."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        self.tracing_client = tracing_client
        self.compiler = compiler
        self.jinja_env = jinja_env
        self.context = Context()
        self.expected_keys = []
        self._langfuse_client = None

    @property
    def langfuse_client(self) -> Langfuse:
        """Lazy-loaded Langfuse client."""
        if self._langfuse_client is None:
            self._langfuse_client = Langfuse()
        return self._langfuse_client

    def execute_actor(self, actor_class, *args) -> Tuple[bool, Any, Optional[str]]:
        """
        Execute an actor with proper error handling.

        Args:
            actor_class: The actor class to instantiate and execute
            *args: Arguments to pass to the actor's execute method

        Returns:
            Tuple of (success, result, error_message)
        """
        try:
            # Create trace and observation IDs
            trace_id = uuid.uuid4().hex
            observation_id = uuid.uuid4().hex

            # Create the actor instance
            actor = actor_class(
                self.tracing_client.m_claude,
                self.compiler,
                self.langfuse_client,
                trace_id,
                observation_id
            )

            # Execute the actor
            result = actor.execute(*args)
            return True, result, None

        except Exception as e:
            logger.error(f"Error executing {actor_class.__name__}: {str(e)}")
            return False, None, f"Error executing {actor_class.__name__}: {str(e)}"

    def create(self, *args, **kwargs) -> StepResult:
        """Create initial implementation."""
        raise NotImplementedError("Subclasses must implement this method")

    def fix(self, *args, **kwargs) -> StepResult:
        """Fix issues found during verification."""
        raise NotImplementedError("Subclasses must implement this method")

    def complete(self, *args, **kwargs) -> StepResult:
        """Mark task as complete."""
        # check if context has all the necessary data
        verified = False
        missing_key = None
        for k in self.expected_keys:
            if self.context.get(k):
                continue
            else:
                missing_key = k
                break
        else:
            verified = True

        self.context.save_locally()

        if verified:
            logger.info("🎉 Successfully completed task 🎉")
            return StepResult(success=True, data=None, error=None)
        else:
            logger.error(f"Missing key: {missing_key}")
            return StepResult(success=False, data=None, error=f"Missing key in context: {missing_key}")

    def start_app_creation(self, app_description: str, output_dir: str) -> StepResult:
        """Start the application creation process."""
        self.context.set("app_description", app_description)
        if not os.path.isabs(output_dir):
            return StepResult(success=False, data=None, error="Output directory must be an absolute path")

        self.context.set("output_dir", output_dir)
        init_prompt = """Follow this workflow to build the complete stack:

        1. First, create a TypeSpec definition:
           - Call make_typespec to generate TypeSpec from the app description
           - If needed, use fix_typespec to fix any issues or address user feedback;

        2. Then, create TypeScript code from the TypeSpec:
           - Call make_typescript to generate TypeScript from the TypeSpec
           - If needed, use fix_typescript to fix any issues or address user feedback;

        3. Next, create a Drizzle database schema:
           - Call make_drizzle to generate a Drizzle schema from the TypeSpec
           - If needed, use fix_drizzle to fix any issues or address user feedback;

        4. Ask user if they want to create handlers. If yes, follow these steps:

            4a. Next, for each feature, create a tests for handlers. Tests are created before the handlers themselves.
                - Call make_handler_test to generate a test for a handler
                - If needed, use fix_handler_test to fix any issues or address user feedback;

            4b. Finally, create handlers for each feature.
                - Call make_handler to generate a handler
                - If needed, use fix_handler to fix any issues or address user feedback;

        Otherwise call complete to finish the task.

        At any point, if you encounter problems that require fixing the TypeSpec, you can go back to
        make_typespec/fix_typespec as needed. Similarly, if TypeScript needs to be
        regenerated after TypeSpec changes, you can do that too. The same applies to handler tests and handlers.

        If the same error persists after three attempts or you're completely stuck, stop and ask for user feedback.
        Call complete only when you have successfully generated and all components.
      """
        return StepResult(success=True, data="The app creation context has been initialized. " + init_prompt, error=None)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for this processor. Override in subclasses."""
        return [
            {
                "name": "complete",
                "description": "signal that the task is complete and no further processing is needed. It will run final checks and return the final result if successful",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "optional completion message"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "start_app_creation",
                "description": "initialize the application creation process",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "app_description": {
                            "type": "string",
                            "description": "description of the application to be created"
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "output directory for saving generated files, absolute path expected"
                        }
                    },
                    "required": ["app_description", "output_dir"]
                }
            },
            {
                "name": "request_human_help",
                "description": "request help from a human when the agent is stuck",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "problem_description": {
                            "type": "string",
                            "description": "description of the problem the agent is facing"
                        },
                        "attempted_tools": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "list of tools the agent has already tried"
                        },
                        "error_details": {
                            "type": "string",
                            "description": "optional details about errors encountered"
                        },
                        "suggested_solutions": {
                            "type": "array",
                            "items": {
                                "type": "string"
                            },
                            "description": "optional list of potential solutions"
                        }
                    },
                    "required": ["problem_description", "attempted_tools"]
                }
            }
        ]

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        return {
            "complete": self.complete,
            "request_human_help": self.escalate,
            "start_app_creation": self.start_app_creation,
        }

    def escalate(
        self,
        problem_description: str,
        attempted_tools: list[str],
        error_details: Optional[str] = None,
        suggested_solutions: Optional[list[str]] = None
    ) -> StepResult:
        """
        Request human help when the agent is stuck.

        Args:
            problem_description: Description of the problem agent is facing
            attempted_tools: List of tools the agent has already tried
            error_details: Optional details about errors encountered
            suggested_solutions: Optional list of potential solutions

        Returns:
            StepResult indicating escalation
        """
        separator = "=" * 80
        logger.critical(separator)
        logger.critical("I HAVE TO SCREAM TO GET ATTENTION")
        logger.critical(separator)
        logger.critical(f"Problem description: {problem_description}")
        logger.critical(f"Attempted tools: {', '.join(attempted_tools)}")

        if error_details:
            logger.critical(f"Error details: {error_details}")

        if suggested_solutions:
            logger.critical("Suggested solutions:")
            for i, solution in enumerate(suggested_solutions, 1):
                logger.critical(f"  {i}. {solution}")

        logger.critical(separator)
        self.context.save_locally()

        # Return result instead of raising an exception to allow for more flexible handling
        return StepResult(
            success=False,
            data={"status": "escalated", "problem": problem_description},
            error="Files saved locally, user intervention required"
        )


class TypeSpecProcessor(Processor):
    """Processor for generating TypeSpec definitions from application descriptions."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for TypeSpec-specific operations."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add TypeSpec-specific tools
        typespec_tools = [
            {
                "name": "make_typespec",
                "description": "generate an initial TypeSpec definition from application description in context (no parameters needed)",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "fix_typespec",
                "description": "try to fix the last TypeSpec definition that failed verification or got additional user feedback",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "additional_feedback": {
                            "type": "string",
                            "description": "optional feedback to help with fixing the TypeSpec"
                        }
                    },
                    "required": []
                }
            }
        ]

        return tools + typespec_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add TypeSpec-specific tool mappings
        typespec_mapping = {
            "make_typespec": self.create,
            "fix_typespec": self.fix
        }

        return {**mapping, **typespec_mapping}

    def create(self) -> StepResult:
        """
        Generate a TypeSpec definition based on an application description.

        Returns:
            StepResult with the generated TypeSpec
        """
        # Get application description from context
        app_description = self.context.get("app_description")
        if not app_description:
            return StepResult(
                success=False,
                data=None,
                error="Application description not found in context. Use start_app_creation first."
            )

        logger.info(f"Generating TypeSpec for application: {app_description}")

        # Execute the TypespecActor
        success, result, error = self.execute_actor(TypespecActor, [app_description])

        if not success or not isinstance(result, tsp.Success):
            return StepResult(
                success=False,
                data=None,
                error=error or f"Failed to generate valid TypeSpec: {result.__class__.__name__ if result else 'None'}"
            )

        # Generate complete typespec content with imports
        typespec_content = "\n".join([
            'import "./helpers.js";',
            "",
            "extern dec llm_func(target: unknown, description: string);",
            "",
            "extern dec scenario(target: unknown, gherkin: string);",
            "",
            result.typespec
        ])

        # Store the results in context
        self.context.set("last_typespec", typespec_content)
        self.context.set("last_typespec_feedback", result.feedback)

        # Set expected keys for this processor
        self.expected_keys = ["last_typespec"]

        return StepResult(
            success=True,
            data={
                "typespec": typespec_content,
                "feedback": result.feedback
            }
        )


    def fix(self, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix a TypeSpec definition that failed verification.

        Args:
            additional_feedback: Optional feedback to help with fixing the TypeSpec

        Returns:
            StepResult with the fixed TypeSpec
        """



class TypeScriptProcessor(Processor):
    """Processor for generating TypeScript code from TypeSpec definitions."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for TypeScript-specific operations."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add TypeScript-specific tools
        typescript_tools = [
            {
                "name": "make_typescript",
                "description": "generate TypeScript code from the last TypeSpec definition in context (no parameters needed)",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },

            {
                "name": "fix_typescript",
                "description": "try to fix the last TypeScript code that failed verification or got user feedback",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "additional_feedback": {
                            "type": "string",
                            "description": "optional feedback to help with fixing the TypeScript"
                        }
                    },
                    "required": []
                }
            }
        ]

        return tools + typescript_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add TypeScript-specific tool mappings
        typescript_mapping = {
            "make_typescript": self.create,
            "fix_typescript": self.fix
        }

        return {**mapping, **typescript_mapping}

    def create(self) -> StepResult:
        """
        Generate TypeScript code based on TypeSpec definitions.

        Returns:
            StepResult with the generated TypeScript code
        """
        typespec = self.context.get("last_typespec")


    def fix(self, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix TypeScript code that failed verification.

        Args:
            additional_feedback: Optional feedback to help with fixing the TypeScript

        Returns:
            StepResult with the fixed TypeScript code
        """


class DrizzleProcessor(Processor):
    """Processor for generating Drizzle database schemas from TypeSpec."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for Drizzle-specific operations."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add Drizzle-specific tools
        drizzle_tools = [
            {
                "name": "make_drizzle",
                "description": "generate an initial drizzle schema from the last typespec in context (no parameters needed)",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "fix_drizzle",
                "description": "try to fix the last drizzle schema that failed verification",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "additional_feedback": {
                            "type": "string",
                            "description": "optional feedback to help with fixing the schema"
                        }
                    },
                    "required": []
                }
            }
        ]

        return tools + drizzle_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add Drizzle-specific tool mappings
        drizzle_mapping = {
            "make_drizzle": self.create,
            "fix_drizzle": self.fix
        }

        return {**mapping, **drizzle_mapping}

    def create(self) -> StepResult:
        """
        Generate a drizzle schema based on TypeSpec definitions.

        Returns:
            StepResult with the generated schema
        """
        typespec = self.context.get("last_typespec")


    def fix(self, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix a drizzle schema that failed verification.

        Args:
            additional_feedback: Optional feedback to help with fixing the schema

        Returns:
            StepResult with the fixed schema
        """
        schema = self.context.get("last_schema")
        error = self.context.get("last_error")




class HandlerProcessor(Processor):
    """Processor for generating handlers for functions defined in TypeScript."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for Handler-specific operations."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add Handler-specific tools
        handler_tools = [
            {
                "name": "make_handler",
                "description": "generate a handler implementation for a function defined in TypeScript schema",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to implement"
                        }
                    },
                    "required": ["function_name"]
                }
            },

            {
                "name": "fix_handler",
                "description": "try to fix the last handler implementation that failed verification",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to fix"
                        },
                        "additional_feedback": {
                            "type": "string",
                            "description": "optional feedback to help with fixing the handler"
                        }
                    },
                    "required": ["function_name"]
                }
            }
        ]

        return tools + handler_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add Handler-specific tool mappings
        handler_mapping = {
            "make_handler": self.create,
            "fix_handler": self.fix
        }

        return {**mapping, **handler_mapping}

    def create(self, function_name: str) -> StepResult:
        """
        Generate a handler implementation for a function.

        Args:
            function_name: Name of the function to implement

        Returns:
            StepResult with the generated handler
        """
        typespec = self.context.get("last_typespec")
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")


    def fix(self, function_name: str, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix a handler implementation that failed verification.

        Args:
            function_name: Name of the function to fix
            additional_feedback: Optional feedback to help with fixing the handler

        Returns:
            StepResult with the fixed handler
        """
        handler = self.context.get(f"handler_{function_name}")
        error = self.context.get("last_error")
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")


class HandlerTestProcessor(Processor):
    """Processor for generating tests for handlers."""

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for HandlerTest-specific operations."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add HandlerTest-specific tools
        handler_test_tools = [
            {
                "name": "make_handler_test",
                "description": "generate tests for a handler implementation",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to test"
                        }
                    },
                    "required": ["function_name"]
                }
            },
            {
                "name": "fix_handler_test",
                "description": "try to fix the last handler test implementation that failed verification",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to fix tests for"
                        },
                        "additional_feedback": {
                            "type": "string",
                            "description": "optional feedback to help with fixing the tests"
                        }
                    },
                    "required": ["function_name"]
                }
            }
        ]

        return tools + handler_test_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add HandlerTest-specific tool mappings
        handler_test_mapping = {
            "make_handler_test": self.create,
            "fix_handler_test": self.fix
        }

        return {**mapping, **handler_test_mapping}

    def create(self, function_name: str) -> StepResult:
        """
        Generate tests for a handler implementation.

        Args:
            function_name: Name of the function to test

        Returns:
            StepResult with the generated tests
        """
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")

    def fix(self, function_name: str, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix tests for a handler implementation that failed verification.

        Args:
            function_name: Name of the function to fix tests for
            additional_feedback: Optional feedback to help with fixing the tests

        Returns:
            StepResult with the fixed tests
        """


class IntegratedProcessor(Processor):
    """
    A processor that integrates all specialized processors (TypeSpec, TypeScript, Drizzle, Handler, HandlerTest)
    to provide a unified interface with access to all tools.
    """

    def __init__(self, tracing_client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        super().__init__(tracing_client, compiler, jinja_env)

        # Create specialized processors
        self.typespec_processor = TypeSpecProcessor(tracing_client, compiler, jinja_env)
        self.typescript_processor = TypeScriptProcessor(tracing_client, compiler, jinja_env)
        self.drizzle_processor = DrizzleProcessor(tracing_client, compiler, jinja_env)
        self.handler_processor = HandlerProcessor(tracing_client, compiler, jinja_env)
        self.handler_test_processor = HandlerTestProcessor(tracing_client, compiler, jinja_env)

        # Share the same context between all processors
        shared_context = self.context
        self.typespec_processor.context = shared_context
        self.typescript_processor.context = shared_context
        self.drizzle_processor.context = shared_context
        self.handler_processor.context = shared_context
        self.handler_test_processor.context = shared_context

        # Now that processors are set up, initialize the tools
        self.tool_definitions = self.get_tool_definitions()
        self.tool_mapping = self.get_tool_mapping()

        self.expected_keys = ["last_typespec", "last_typescript", "last_schema"]


    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions from all specialized processors."""
        # Get base tools from parent class
        tools = super().get_tool_definitions()

        # Add all specialized processor tools
        typespec_tools = self.typespec_processor.get_tool_definitions()[len(tools):]
        typescript_tools = self.typescript_processor.get_tool_definitions()[len(tools):]
        drizzle_tools = self.drizzle_processor.get_tool_definitions()[len(tools):]
        handler_tools = self.handler_processor.get_tool_definitions()[len(tools):]
        handler_test_tools = self.handler_test_processor.get_tool_definitions()[len(tools):]

        return tools + typespec_tools + typescript_tools + drizzle_tools + handler_tools + handler_test_tools

    def get_tool_mapping(self) -> Dict[str, Callable]:
        """Get mapping from tool names to implementation methods from all specialized processors."""
        # Get base tool mapping from parent class
        mapping = super().get_tool_mapping()

        # Add all specialized processor mappings
        typespec_mapping = {k: v for k, v in self.typespec_processor.get_tool_mapping().items()
                           if k not in mapping}
        typescript_mapping = {k: v for k, v in self.typescript_processor.get_tool_mapping().items()
                             if k not in mapping}
        drizzle_mapping = {k: v for k, v in self.drizzle_processor.get_tool_mapping().items()
                          if k not in mapping}
        handler_mapping = {k: v for k, v in self.handler_processor.get_tool_mapping().items()
                          if k not in mapping}
        handler_test_mapping = {k: v for k, v in self.handler_test_processor.get_tool_mapping().items()
                              if k not in mapping}

        return {**mapping, **typespec_mapping, **typescript_mapping, **drizzle_mapping,
                **handler_mapping, **handler_test_mapping}
