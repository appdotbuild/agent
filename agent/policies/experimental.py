from dataclasses import dataclass
from typing import Optional, Any, Dict, Callable, List, Tuple
import jinja2
import threading
from anthropic.types import MessageParam
from anthropic import AnthropicBedrock
import os
from tracing_client import TracingClient
from compiler.core import Compiler
from policies import drizzle
from policies import typespec as tsp
from policies import typescript as ts
from policies.handlers import HandlerTaskNode, PROMPT as HANDLER_PROMPT, FIX_PROMPT as HANDLER_FIX_PROMPT
from policies.handler_tests import HandlerTestTaskNode, PROMPT as HANDLER_TEST_PROMPT, FIX_PROMPT as HANDLER_TEST_FIX_PROMPT
from application import langfuse_context
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

    def create(self, *args, **kwargs) -> StepResult:
        """Create initial implementation."""
        raise NotImplementedError("Subclasses must implement this method")

    def verify(self, *args, **kwargs) -> StepResult:
        """Verify implementation with tests or compilation."""
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
           - Call verify_typespec to check if it's valid
           - If needed, use fix_typespec to fix any issues or address user feedback;

        2. Then, create TypeScript code from the TypeSpec:
           - Call make_typescript to generate TypeScript from the TypeSpec
           - Call verify_typescript to check if it's valid
           - If needed, use fix_typescript to fix any issues or address user feedback;

        3. Next, create a Drizzle database schema:
           - Call make_drizzle to generate a Drizzle schema from the TypeSpec
           - Call verify_drizzle to check if it's valid
           - If needed, use fix_drizzle to fix any issues or address user feedback;

        4. Ask user if they want to create handlers. If yes, follow these steps:

            4a. Next, for each feature, create a tests for handlers. Tests are created before the handlers themselves.
                - Call make_handler_test to generate a test for a handler
                - Call verify_handler_test to check if it's valid
                - If needed, use fix_handler_test to fix any issues or address user feedback;

            4b. Finally, create handlers for each feature.
                - Call make_handler to generate a handler
                - Call verify_handler to check if it's valid
                - If needed, use fix_handler to fix any issues or address user feedback;

        Otherwise call complete to finish the task.

        At any point, if you encounter problems that require fixing the TypeSpec, you can go back to
        make_typespec/fix_typespec/verify_typespec as needed. Similarly, if TypeScript needs to be
        regenerated after TypeSpec changes, you can do that too. The same applies to handler tests and handlers.

        If the same error persists after three attempts or you're completely stuck, stop and ask for user feedback.
        Call complete only when you have successfully generated and verified all three components.
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
                "name": "verify_typespec",
                "description": "verify if the last TypeSpec definition in context is valid (no parameters needed)",
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
            "verify_typespec": self.verify,
            "fix_typespec": self.fix
        }

        return {**mapping, **typespec_mapping}

    def create(self) -> StepResult:
        """
        Generate a TypeSpec definition based on an application description.

        Returns:
            StepResult with the generated TypeSpec
        """
        app_description = self.context.get("app_description")
        logger.info(f"[make_typespec] Generating TypeSpec from description, length: {len(app_description)}")

        with tsp.TypespecTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            # Prepare prompt with application description
            template = self.jinja_env.from_string(tsp.PROMPT)
            prompt = template.render(application_description=app_description)

            logger.info("[make_typespec] Running TypespecTaskNode")
            result = tsp.TypespecTaskNode.run(
                [{"role": "user", "content": prompt}],
                init=True
            )

            if isinstance(result.output, Exception):
                logger.error(f"[make_typespec] Error: {str(result.output)}")
                error_msg = str(result.output)
                self.context.set("last_error", error_msg)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            # Check if there's a compile error in the feedback
            if result.output.feedback["exit_code"] != 0:
                error_msg = result.output.feedback["stdout"]
                logger.error(f"[make_typespec] Compilation error: {error_msg[:100]}...")
                self.context.set("last_error", error_msg)
                self.context.set("last_typespec", result.output.typespec_definitions)
                return StepResult(
                    success=False,
                    data={
                        "reasoning": result.output.reasoning,
                        "typespec": result.output.typespec_definitions,
                        "llm_functions": [f.name for f in result.output.llm_functions]
                    },
                    error=error_msg
                )

            logger.info("[make_typespec] Successfully generated TypeSpec")
            typespec = result.output.typespec_definitions
            self.context.set("last_typespec", typespec)
            self.context.set("llm_functions", result.output.llm_functions)

            return StepResult(
                success=True,
                data={
                    "reasoning": result.output.reasoning,
                    "typespec": typespec,
                    "llm_functions": [f.name for f in result.output.llm_functions]
                }
            )

    def verify(self) -> StepResult:
        """
        Verify a TypeSpec definition by compiling it.

        Returns:
            StepResult with compilation results
        """
        typespec = self.context.get("last_typespec")
        logger.info(f"[verify_typespec] Verifying TypeSpec, length: {len(typespec)}")

        # Prepare the TypeSpec for compilation
        typespec_schema = "\n".join([
            'import "./helpers.js";',
            "",
            "extern dec llm_func(target: unknown, description: string);",
            "",
            "extern dec scenario(target: unknown, gherkin: string);",
            "",
            typespec
        ])

        result = self.compiler.compile_typespec(typespec_schema)
        logger.info(f"[verify_typespec] Compile result: exit_code={result['exit_code']}")

        # Check success
        success = result["exit_code"] == 0

        # Extract error message if any
        error = None
        if not success:
            if result["stdout"]:
                error = result["stdout"]
                logger.error(f"[verify_typespec] Error in stdout: {error[:100]}...")

            # Store error in context
            self.context.set("last_error", error)
        else:
            logger.info("[verify_typespec] TypeSpec verified successfully")

        return StepResult(success=success, data=result, error=error)

    def fix(self, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix a TypeSpec definition that failed verification.

        Args:
            additional_feedback: Optional feedback to help with fixing the TypeSpec

        Returns:
            StepResult with the fixed TypeSpec
        """
        typespec = self.context.get("last_typespec")
        error = self.context.get("last_error") or ""
        logger.info(f"[fix_typespec] Attempting to fix TypeSpec, error length: {len(error)}")

        if additional_feedback:
            logger.info(f"[fix_typespec] Additional feedback provided: {additional_feedback}")

        if not error and not additional_feedback:
            raise RuntimeError("No error or additional feedback provided, cannot fix TypeSpec")

        with tsp.TypespecTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            render_params = {
                "errors": error,
                "typespec": typespec
            }

            if additional_feedback is not None:
                render_params["additional_feedback"] = additional_feedback

            logger.info(f"[fix_typespec] Rendering template with params: {render_params.keys()}")
            fix_template = self.jinja_env.from_string(tsp.FIX_PROMPT)
            fix_content = fix_template.render(**render_params)

            logger.info("[fix_typespec] Running TypespecTaskNode to fix TypeSpec")
            result = tsp.TypespecTaskNode.run(
                [{"role": "user", "content": fix_content}],
                init=True
            )

            if isinstance(result.output, Exception):
                logger.error(f"[fix_typespec] Error: {str(result.output)}")
                error_msg = str(result.output)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            logger.info("[fix_typespec] Successfully processed fix request")
            fixed_typespec = result.output.typespec_definitions
            self.context.set("last_typespec", fixed_typespec)
            self.context.set("llm_functions", result.output.llm_functions)

            return StepResult(
                success=True,
                data={
                    "reasoning": result.output.reasoning,
                    "typespec": fixed_typespec,
                    "llm_functions": [f.name for f in result.output.llm_functions],
                    "status": "probably fixed, need to verify"
                },
                error=None
            )


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
                "name": "verify_typescript",
                "description": "verify if the last TypeScript code in context is valid (no parameters needed)",
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
            "verify_typescript": self.verify,
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
        logger.info(f"[make_typescript] Generating TypeScript from TypeSpec, length: {len(typespec)}")

        with ts.TypescriptTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            # Prepare prompt with TypeSpec definitions
            template = self.jinja_env.from_string(ts.PROMPT)
            prompt = template.render(typespec_definitions=typespec)

            logger.info("[make_typescript] Running TypescriptTaskNode")
            result = ts.TypescriptTaskNode.run(
                [{"role": "user", "content": prompt}],
                init=True
            )

            if isinstance(result.output, Exception):
                logger.error(f"[make_typescript] Error: {str(result.output)}")
                error_msg = str(result.output)
                self.context.set("last_error", error_msg)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            # Check if there's a compile error in the feedback
            if result.output.feedback["exit_code"] != 0:
                error_msg = result.output.feedback["stdout"]
                logger.error(f"[make_typescript] Compilation error: {error_msg[:100]}...")
                self.context.set("last_error", error_msg)
                self.context.set("last_typescript", result.output.typescript_schema)
                return StepResult(
                    success=False,
                    data={
                        "reasoning": result.output.reasoning,
                        "typescript": result.output.typescript_schema,
                        "functions": [f.name for f in result.output.functions]
                    },
                    error=error_msg
                )

            logger.info("[make_typescript] Successfully generated TypeScript")
            typescript = result.output.typescript_schema
            self.context.set("last_typescript", typescript)
            self.context.set("functions", result.output.functions)
            self.context.set("type_to_zod", result.output.type_to_zod)

            return StepResult(
                success=True,
                data={
                    "reasoning": result.output.reasoning,
                    "typescript": typescript,
                    "functions": [f.name for f in result.output.functions]
                }
            )

    def verify(self) -> StepResult:
        """
        Verify TypeScript code by compiling it.

        Returns:
            StepResult with compilation results
        """
        typescript = self.context.get("last_typescript")
        logger.info(f"[verify_typescript] Verifying TypeScript, length: {len(typescript)}")

        result = self.compiler.compile_typescript({"src/common/schema.ts": typescript})
        logger.info(f"[verify_typescript] Compile result: exit_code={result['exit_code']}")

        # Check success
        success = result["exit_code"] == 0

        # Extract error message if any
        error = None
        if not success:
            if result["stdout"]:
                error = result["stdout"]
                logger.error(f"[verify_typescript] Error in stdout: {error[:100]}...")

            # Store error in context
            self.context.set("last_error", error)
        else:
            logger.info("[verify_typescript] TypeScript verified successfully")

        return StepResult(success=success, data=result, error=error)

    def fix(self, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix TypeScript code that failed verification.

        Args:
            additional_feedback: Optional feedback to help with fixing the TypeScript

        Returns:
            StepResult with the fixed TypeScript code
        """
        typescript = self.context.get("last_typescript")
        error = self.context.get("last_error")
        logger.info(f"[fix_typescript] Attempting to fix TypeScript, error length: {len(error)}")

        if additional_feedback:
            logger.info(f"[fix_typescript] Additional feedback provided: {additional_feedback}")

        with ts.TypescriptTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            render_params = {
                "errors": error,
                "typescript": typescript
            }

            if additional_feedback is not None:
                render_params["additional_feedback"] = additional_feedback

            logger.info(f"[fix_typescript] Rendering template with params: {render_params.keys()}")
            fix_template = self.jinja_env.from_string(ts.FIX_PROMPT)
            fix_content = fix_template.render(**render_params)

            logger.info("[fix_typescript] Running TypescriptTaskNode to fix TypeScript")
            result = ts.TypescriptTaskNode.run(
                [{"role": "user", "content": fix_content}],
                init=True
            )

            if isinstance(result.output, Exception):
                logger.error(f"[fix_typescript] Error: {str(result.output)}")
                error_msg = str(result.output)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            logger.info("[fix_typescript] Successfully processed fix request")
            fixed_typescript = result.output.typescript_schema
            self.context.set("last_typescript", fixed_typescript)
            self.context.set("functions", result.output.functions)
            self.context.set("type_to_zod", result.output.type_to_zod)

            return StepResult(
                success=True,
                data={
                    "reasoning": result.output.reasoning,
                    "typescript": fixed_typescript,
                    "functions": [f.name for f in result.output.functions],
                    "status": "probably fixed, need to verify"
                },
                error=None
            )


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
                "name": "verify_drizzle",
                "description": "verify if the last drizzle schema in context is valid (no parameters needed)",
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
            "verify_drizzle": self.verify,
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

        logger.info(f"[make_drizzle] Generating schema from typespec, length: {len(typespec)}")
        # Create the task platform
        with drizzle.DrizzleTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            # Prepare prompt with TypeSpec definitions
            template = self.jinja_env.from_string(drizzle.PROMPT)
            prompt = template.render(typespec_definitions=typespec)

            logger.info("[make_drizzle] Running DrizzleTaskNode")
            result = drizzle.DrizzleTaskNode.run(
                [{"role": "user", "content": prompt}],
                init=True
            )

            if isinstance(result.output, Exception):
                logger.error(f"[make_drizzle] Error: {str(result.output)}")
                error_msg = str(result.output.feedback)
                self.context.set("last_error", error_msg)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            logger.info("[make_drizzle] Successfully generated schema")
            # break it on purpose once, to test the fix tool
            if not "drizzle-orm/pg-core" in result.output.drizzle_schema:
                raise RuntimeError("Wow, not sure how to break it!")
            schema = result.output.drizzle_schema.replace("drizzle-orm/pg-core", "drizzle-orm/pg-kozel")
            self.context.set("last_schema", schema)

            return StepResult(
                success=True,
                data={
                    "schema": schema,
                }
            )

    def verify(self) -> StepResult:
        """
        Verify a drizzle schema by compiling it.

        Returns:
            StepResult with compilation results
        """
        schema = self.context.get("last_schema")
        logger.info(f"[verify_drizzle] Verifying schema, length: {len(schema)}")
        result = self.compiler.compile_drizzle(schema)
        logger.info(f"[verify_drizzle] Compile result: exit_code={result['exit_code']}")

        # Store schema in context
        self.context.set("last_schema", schema)

        # Check success
        success = (
            result["exit_code"] == 0 and
            result["stderr"] is None
        )

        # Extract error message if any
        error = None
        if not success:
            if result["stderr"]:
                error = result["stderr"]
                logger.error(f"[verify_drizzle] Error in stderr: {error[:100]}...")
            elif result["stdout"] and result["exit_code"] != 0:
                error = result["stdout"]
                logger.error(f"[verify_drizzle] Error in stdout: {error[:100]}...")

            # Store error in context
            self.context.set("last_error", error)
        else:
            logger.info("[verify_drizzle] Schema verified successfully")

        return StepResult(success=success, data=result, error=error)

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
        logger.info(f"[fix_drizzle] Attempting to fix schema, error length: {len(error)}")

        if additional_feedback:
            logger.info(f"[fix_drizzle] Additional feedback provided: {additional_feedback}")


        with drizzle.DrizzleTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            render_params = {
                "errors": error,
                "schema": schema
            }

            if additional_feedback is not None:
                render_params["additional_feedback"] = additional_feedback

            logger.info(f"[fix_drizzle] Rendering template with params: {render_params.keys()}")
            fix_template = self.jinja_env.from_string(drizzle.FIX_PROMPT)
            fix_content = fix_template.render(**render_params)

            logger.info("[fix_drizzle] Running DrizzleTaskNode to fix schema")
            result = drizzle.DrizzleTaskNode.run(
                [{"role": "user", "content": fix_content}],
                init=True
            ).output.drizzle_schema
            logger.info("[fix_drizzle] Successfully processed fix request")

            # Store the fixed schema in context
            self.context.set("last_schema", result)

            return StepResult(success=True, data={"schema": result, "status": "probably fixed, need to verify"}, error=None)


def run_with_claude(processor: Processor, client: AnthropicBedrock, messages: List[MessageParam]) -> Tuple[List[MessageParam], bool]:
    """
    Send messages to Claude with tool definitions and process tool use responses.

    Args:
        processor: Processor instance with tool implementation
        client: AnthropicBedrock client instance
        messages: List of messages to send to Claude

    Returns:
        Tuple of (followup_messages, is_complete)
    """
    response = client.messages.create(
        messages=messages,
        max_tokens=1024 * 16,
        # model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        model="anthropic.claude-3-5-haiku-20241022-v1:0",
        stream=False,
        tools=processor.tool_definitions,
    )

    # Record if any tool was used (requiring further processing)
    is_complete = True
    tool_results = []

    # Process all content blocks in the response
    for message in response.content:
        if message.type == "text":
            is_complete = True  # No tools used, so the task is complete
            logger.info(f"[Claude Response] Message: {message.text}")
        elif message.type == "tool_use":
            is_complete = False  # Tool was used, so we need to continue
            tool_use = message.to_dict()
            logger.info(f"[Claude Response] Tool use: {tool_use['name']}")

            tool_params = tool_use['input']
            tool_method = processor.tool_mapping.get(tool_use['name'])

            if tool_method:
                result = tool_method(**tool_params)
                logger.info(f"[Claude Response] Tool result: {result.to_dict()}")

                if tool_use["name"] == "complete" and result.success:
                    is_complete = True
                    continue

                # Create a new message with the tool results
                tool_results.append({
                    "tool": tool_use['name'],
                    "result": result.to_dict()
                })
            else:
                logger.error(f"[Claude Response] Unknown tool: {tool_use['name']}")
                tool_results.append({
                    "tool": tool_use['name'],
                    "result": {"success": False, "error": f"Unknown tool '{tool_use['name']}'"}
                })

    # Create a single new message with all tool results
    if tool_results:
        new_message = {
            "role": "user",
            "content": f"Tool results:\n{tool_results}\n\nPlease continue based on these results."
        }
        return messages + [new_message], is_complete
    else:
        # No tools were used or complete was called
        return messages, is_complete


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
                "name": "verify_handler",
                "description": "verify if the last handler implementation is valid",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to verify"
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
            "verify_handler": self.verify,
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

        logger.info(f"[make_handler] Generating handler for function: {function_name}")

        with HandlerTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            # Prepare prompt with schemas
            template = self.jinja_env.from_string(HANDLER_PROMPT)
            prompt = template.render(
                function_name=function_name,
                typesspec_schema=typespec,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            logger.info("[make_handler] Running HandlerTaskNode")
            result = HandlerTaskNode.run(
                [{"role": "user", "content": prompt}],
                init=True,
                function_name=function_name,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            if isinstance(result.output, Exception):
                logger.error(f"[make_handler] Error: {str(result.output)}")
                error_msg = str(result.output)
                self.context.set("last_error", error_msg)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            # Check if there's a compile error
            if result.output.feedback["exit_code"] != 0:
                error_msg = result.output.feedback["stdout"]
                logger.error(f"[make_handler] Compilation error: {error_msg[:100]}...")
                self.context.set("last_error", error_msg)
                self.context.set(f"handler_{function_name}", result.output.handler)
                return StepResult(
                    success=False,
                    data={
                        "function_name": function_name,
                        "handler": result.output.handler
                    },
                    error=error_msg
                )

            logger.info(f"[make_handler] Successfully generated handler for {function_name}")
            handler = result.output.handler
            self.context.set(f"handler_{function_name}", handler)
            self.context.set("last_handler_function", function_name)

            return StepResult(
                success=True,
                data={
                    "function_name": function_name,
                    "handler": handler
                }
            )

    def verify(self, function_name: str) -> StepResult:
        """
        Verify a handler implementation by compiling it.

        Args:
            function_name: Name of the function to verify

        Returns:
            StepResult with compilation results
        """
        handler = self.context.get(f"handler_{function_name}")
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")

        if not handler:
            return StepResult(
                success=False,
                data=None,
                error=f"No handler found for function: {function_name}"
            )

        logger.info(f"[verify_handler] Verifying handler for {function_name}, length: {len(handler)}")

        files = {
            f"src/handlers/{function_name}.ts": handler,
            "src/common/schema.ts": typescript,
            "src/db/schema/application.ts": drizzle_schema,
        }

        result = self.compiler.compile_typescript(files)[0]
        logger.info(f"[verify_handler] Compile result: exit_code={result['exit_code']}")

        # Check success
        success = result["exit_code"] == 0

        # Extract error message if any
        error = None
        if not success:
            if result["stdout"]:
                error = result["stdout"]
                logger.error(f"[verify_handler] Error in stdout: {error[:100]}...")

            # Store error in context
            self.context.set("last_error", error)
        else:
            logger.info(f"[verify_handler] Handler for {function_name} verified successfully")

        return StepResult(success=success, data=result, error=error)

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

        if not handler:
            return StepResult(
                success=False,
                data=None,
                error=f"No handler found for function: {function_name}"
            )

        logger.info(f"[fix_handler] Attempting to fix handler for {function_name}, error length: {len(error)}")

        if additional_feedback:
            logger.info(f"[fix_handler] Additional feedback provided: {additional_feedback}")

        with HandlerTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            render_params = {
                "errors": error,
                "handler": handler
            }

            if additional_feedback is not None:
                render_params["additional_feedback"] = additional_feedback

            logger.info(f"[fix_handler] Rendering template with params: {render_params.keys()}")
            fix_template = self.jinja_env.from_string(HANDLER_FIX_PROMPT)
            fix_content = fix_template.render(**render_params)

            logger.info(f"[fix_handler] Running HandlerTaskNode to fix handler for {function_name}")
            result = HandlerTaskNode.run(
                [
                    {"role": "user", "content": f"Original handler for {function_name}:\n\n<handler>{handler}</handler>"},
                    {"role": "user", "content": fix_content}
                ],
                init=True,
                function_name=function_name,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            if isinstance(result.output, Exception):
                logger.error(f"[fix_handler] Error: {str(result.output)}")
                error_msg = str(result.output)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            logger.info(f"[fix_handler] Successfully processed fix request for {function_name}")
            fixed_handler = result.output.handler
            self.context.set(f"handler_{function_name}", fixed_handler)

            return StepResult(
                success=True,
                data={
                    "function_name": function_name,
                    "handler": fixed_handler,
                    "status": "probably fixed, need to verify"
                },
                error=None
            )


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
                "name": "verify_handler_test",
                "description": "verify if the last handler test implementation is valid",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "name of the function to verify tests for"
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
            "verify_handler_test": self.verify,
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

        # FixMe: TDD - we want to generate tests before implementing handlers
        # No need to check for existing handler since we're promoting test-first approach
        logger.info(f"[make_handler_test] Generating tests for function: {function_name}")

        with HandlerTestTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            # Prepare prompt with schemas
            template = self.jinja_env.from_string(HANDLER_TEST_PROMPT)
            prompt = template.render(
                function_name=function_name,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            logger.info("[make_handler_test] Running HandlerTestTaskNode")
            result = HandlerTestTaskNode.run(
                [{"role": "user", "content": prompt}],
                init=True,
                function_name=function_name,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            if isinstance(result.output, Exception):
                logger.error(f"[make_handler_test] Error: {str(result.output)}")
                error_msg = str(result.output)
                self.context.set("last_error", error_msg)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            # Check if there's a compile error
            if result.output.feedback["exit_code"] != 0:
                error_msg = result.output.feedback["stdout"]
                logger.error(f"[make_handler_test] Compilation error: {error_msg[:100]}...")
                self.context.set("last_error", error_msg)
                self.context.set(f"handler_test_{function_name}", result.output.content)
                return StepResult(
                    success=False,
                    data={
                        "function_name": function_name,
                        "test_content": result.output.content,
                        "imports": result.output.imports,
                        "tests": result.output.tests
                    },
                    error=error_msg
                )

            logger.info(f"[make_handler_test] Successfully generated tests for {function_name}")
            test_content = result.output.content
            self.context.set(f"handler_test_{function_name}", test_content)

            return StepResult(
                success=True,
                data={
                    "function_name": function_name,
                    "test_content": test_content,
                    "imports": result.output.imports,
                    "tests": result.output.tests
                }
            )

    def verify(self, function_name: str) -> StepResult:
        """
        Verify tests for a handler implementation by compiling them.

        Args:
            function_name: Name of the function to verify tests for

        Returns:
            StepResult with compilation results
        """
        test_content = self.context.get(f"handler_test_{function_name}")
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")

        if not test_content:
            return StepResult(
                success=False,
                data=None,
                error=f"No tests found for function: {function_name}"
            )

        logger.info(f"[verify_handler_test] Verifying tests for {function_name}")

        # FixMe: TDD approach - we're creating a stub handler to verify tests
        # This allows tests to be created before implementing the handler function
        stub_handler = f"""
import {{ db }} from "../db";
import {{ {function_name} }} from "../common/schema";

export const handle = {function_name};
"""

        files = {
            f"src/handlers/{function_name}.ts": stub_handler,
            f"src/tests/handlers/{function_name}.test.ts": test_content,
            "src/common/schema.ts": typescript,
            "src/db/schema/application.ts": drizzle_schema,
        }

        linting_cmd = ["npx", "eslint", "-c", ".eslintrc.js", f"./src/tests/handlers/{function_name}.test.ts"]
        compilation_result, linting_result = self.compiler.compile_typescript(files, [linting_cmd])

        combined_feedback = {
            "exit_code": compilation_result["exit_code"] or linting_result["exit_code"],
            "stdout": (compilation_result["stdout"] or "") + ("\n" + linting_result["stdout"] if linting_result["stdout"] else ""),
            "stderr": (compilation_result["stderr"] or "") + ("\n" + linting_result["stderr"] if linting_result["stderr"] else "")
        }

        logger.info(f"[verify_handler_test] Compile result: exit_code={combined_feedback['exit_code']}")

        # Check success
        success = combined_feedback["exit_code"] == 0

        # Extract error message if any
        error = None
        if not success:
            if combined_feedback["stdout"]:
                error = combined_feedback["stdout"]
                logger.error(f"[verify_handler_test] Error in stdout: {error[:100]}...")
            elif combined_feedback["stderr"]:
                error = combined_feedback["stderr"]
                logger.error(f"[verify_handler_test] Error in stderr: {error[:100]}...")

            # Store error in context
            self.context.set("last_error", error)
        else:
            logger.info(f"[verify_handler_test] Tests for {function_name} verified successfully")

        return StepResult(success=success, data=combined_feedback, error=error)

    def fix(self, function_name: str, additional_feedback: Optional[str] = None) -> StepResult:
        """
        Attempt to fix tests for a handler implementation that failed verification.

        Args:
            function_name: Name of the function to fix tests for
            additional_feedback: Optional feedback to help with fixing the tests

        Returns:
            StepResult with the fixed tests
        """
        test_content = self.context.get(f"handler_test_{function_name}")
        error = self.context.get("last_error")
        typescript = self.context.get("last_typescript")
        drizzle_schema = self.context.get("last_schema")

        if not test_content:
            return StepResult(
                success=False,
                data=None,
                error=f"No tests found for function: {function_name}"
            )

        logger.info(f"[fix_handler_test] Attempting to fix tests for {function_name}, error length: {len(error)}")

        if additional_feedback:
            logger.info(f"[fix_handler_test] Additional feedback provided: {additional_feedback}")

        with HandlerTestTaskNode.platform(self.tracing_client, self.compiler, self.jinja_env):
            render_params = {
                "errors": error,
                "imports": "",  # Pass empty imports
                "handler_test": test_content
            }

            if additional_feedback is not None:
                render_params["additional_feedback"] = additional_feedback

            logger.info(f"[fix_handler_test] Rendering template with params: {render_params.keys()}")
            fix_template = self.jinja_env.from_string(HANDLER_TEST_FIX_PROMPT)
            fix_content = fix_template.render(**render_params)

            logger.info(f"[fix_handler_test] Running HandlerTestTaskNode to fix tests for {function_name}")
            result = HandlerTestTaskNode.run(
                [
                    {"role": "user", "content": f"Original tests for {function_name}:\n\n```typescript\n{test_content}\n```"},
                    {"role": "user", "content": fix_content}
                ],
                init=True,
                function_name=function_name,
                typescript_schema=typescript,
                drizzle_schema=drizzle_schema
            )

            if isinstance(result.output, Exception):
                logger.error(f"[fix_handler_test] Error: {str(result.output)}")
                error_msg = str(result.output)
                return StepResult(
                    success=False,
                    data=None,
                    error=error_msg
                )

            logger.info(f"[fix_handler_test] Successfully processed fix request for {function_name}")
            fixed_tests = result.output.content
            self.context.set(f"handler_test_{function_name}", fixed_tests)

            return StepResult(
                success=True,
                data={
                    "function_name": function_name,
                    "test_content": fixed_tests,
                    "imports": result.output.imports,
                    "tests": result.output.tests,
                    "status": "probably fixed, need to verify"
                },
                error=None
            )


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
