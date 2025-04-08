from typing import Literal, TypedDict
from dataclasses import dataclass


@dataclass
class LLMFunction:
    name: str
    description: str
    scenario: str


@dataclass
class TypespecOut:
    reasoning: str | None
    typespec_definitions: str | None
    llm_functions: list[LLMFunction] | None
    error_output: str | None


@dataclass
class TypescriptFunction:
    name: str
    argument_type: str
    argument_schema: str
    return_type: str


@dataclass
class TypescriptOut:
    reasoning: str | None
    typescript_schema: str | None
    functions: list[TypescriptFunction] | None
    error_output: str | None


@dataclass
class GherkinOut:
    reasoning: str | None
    gherkin: str | None
    error_output: str | None


@dataclass
class DrizzleOut:
    reasoning: str | None
    drizzle_schema: str | None
    error_output: str | None


class RouterFunc(TypedDict):
    name: str
    description: str
    examples: list[str]


@dataclass
class RouterOut:
    functions: list[RouterFunc] | None
    error_output: str | None


@dataclass
class HandlerTestsOut:
    name: str | None
    content: str | None
    error_output: str | None


@dataclass
class HandlerOut:
    name: str | None
    handler: str | None
    argument_schema: str | None
    error_output: str | None


@dataclass
class RefineOut:
    refined_description: str
    error_output: str | None

@dataclass
class CapabilitiesOut:
    capabilities: list[str]
    error_output: str | None

@dataclass
class ApplicationPrepareOut:
    refined_description: RefineOut
    capabilities: CapabilitiesOut
    typespec: TypespecOut
    status: Literal['success', 'error', 'review', 'processing']

@dataclass
class ApplicationOut:
    refined_description: RefineOut
    capabilities: CapabilitiesOut
    typespec: TypespecOut
    drizzle: DrizzleOut
    handlers: dict[str, HandlerOut]
    handler_tests: dict[str, HandlerTestsOut]
    typescript_schema: TypescriptOut
    gherkin: GherkinOut
    trace_id: str
    
    @classmethod
    def from_context(cls, 
                    result: dict, 
                    capabilities: list[str] | None = None, 
                    trace_id: str | None = None, 
                    error_output: str | None = None) -> 'ApplicationOut':
        """
        Creates an ApplicationOut object from FSM context result.
        
        Args:
            result: The FSM context result dictionary
            capabilities: Optional list of capabilities
            trace_id: Optional trace ID for tracking
            error_output: Optional error message if something went wrong
            
        Returns:
            ApplicationOut object with all the generated artifacts
        """
        # Create TypescriptOut conditionally
        typescript_result = result.get("typescript_schema")
        typescript_out = None
        typescript_args = {}
        
        if typescript_result:
            typescript_out = TypescriptOut(
                reasoning=getattr(typescript_result, "reasoning", None),
                typescript_schema=getattr(typescript_result, "typescript_schema", None),
                functions=getattr(typescript_result, "functions", None),
                error_output=error_output
            )
            typescript_args = {f.name: f.argument_schema for f in typescript_result.functions} if hasattr(typescript_result, "functions") and typescript_result.functions else {}
        
        # Create dictionary comprehensions for handlers and tests
        handler_tests_dict = {
            name: HandlerTestsOut(
                name=name,
                content=getattr(test, "source", None),
                error_output=error_output
            ) for name, test in result.get("handler_tests", {}).items()
        }

        handlers_dict = {
            name: HandlerOut(
                name=name,
                handler=getattr(handler, "source", None),
                argument_schema=typescript_args.get(name),
                error_output=error_output
            ) for name, handler in result.get("handlers", {}).items()
        }

        return cls(
            refined_description=RefineOut(refined_description="", error_output=error_output),
            capabilities=CapabilitiesOut(capabilities if capabilities is not None else [], error_output),
            typespec=TypespecOut(
                reasoning=getattr(result.get("typespec_schema"), "reasoning", None),
                typespec_definitions=getattr(result.get("typespec_schema"), "typespec", None),
                llm_functions=getattr(result.get("typespec_schema"), "llm_functions", None),
                error_output=error_output
            ),
            drizzle=DrizzleOut(
                reasoning=getattr(result.get("drizzle_schema"), "reasoning", None),
                drizzle_schema=getattr(result.get("drizzle_schema"), "drizzle_schema", None),
                error_output=error_output
            ),
            handlers=handlers_dict,
            handler_tests=handler_tests_dict,
            typescript_schema=typescript_out,
            gherkin=GherkinOut(reasoning=None, gherkin=None, error_output=error_output),
            trace_id=trace_id
        )