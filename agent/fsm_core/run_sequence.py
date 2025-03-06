from typing import Callable
from anthropic import AnthropicBedrock
from anthropic.types import MessageParam
from ..compiler.core import Compiler

from langfuse import Langfuse
from langfuse.client import StatefulGenerationClient
from langfuse.decorators import observe, langfuse_context

from .common import AgentState, Node
from . import common, typespec, drizzle, typescript, handler_tests, handlers


class Context:
    def __init__(self, compiler: Compiler):
        self.compiler = compiler


def bedrock_claude(
    client: AnthropicBedrock,
    messages: list[MessageParam],
    model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    max_tokens: int = 8192,
    temperature: float = 1.0,
    thinking_budget: int = 0,
):
    if thinking_budget > 0:
        thinking_config = {
            "type": "enabled",
            "budget_tokens": thinking_budget,
        }
    else:
        thinking_config = {
            "type": "disabled",
        }
    return client.messages.create(
        max_tokens=max_tokens + thinking_budget,
        model=model,
        messages=messages,
        temperature=temperature,
        thinking=thinking_config,
    )


def span_claude_bedrock(
    client: AnthropicBedrock,
    messages: list[MessageParam],
    generation: StatefulGenerationClient,
    model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    max_tokens: int = 8192,
    temperature: float = 1.0,
    thinking_budget: int = 0,
):
    generation.update(
        name="Anthropic-generation",
        input=messages,
        model=model,
        model_parameters={
            "maxTokens": max_tokens,
            "temperature": temperature,
            "thinkingBudget": thinking_budget,
        },
    )
    completion = bedrock_claude(
        client,
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_budget=thinking_budget,
    )
    generation.end(
        output=MessageParam(role="assistant", content=completion.content),
        usage={
            "input": completion.usage.input_tokens,
            "output": completion.usage.output_tokens,
        }
    )
    return completion


def langfuse_expand[T](
    context: T,
    llm_fn: Callable[[list[MessageParam], StatefulGenerationClient], MessageParam],
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
) -> Callable[[Node[AgentState[T]]], Node[AgentState[T]]]:
    def expand_fn(node: Node[AgentState[T]]) -> Node[AgentState[T]]:
        span = langfuse.span(
            trace_id=langfuse_parent_trace_id,
            parent_observation_id=node._id if node.parent else langfuse_parent_observation_id,
            name="expand",
        )
        message = llm_fn([m for n in node.get_trajectory() for m in n.data.thread], span.generation())
        new_node = Node(AgentState(node.data.inner.on_message(context, message), message), parent=node, id=span.id)
        span.end(
            output=new_node.data.inner.__dict__, # check
            metadata={"child_node_id": new_node._id, "parent_node_id": node._id},
        )
        return new_node
    return expand_fn


def agent_dfs[T](
    init: common.AgentMachine[T],
    context: T,
    llm_fn: Callable[[list[MessageParam], StatefulGenerationClient], MessageParam],
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
    max_depth: int = 5,
    max_width: int = 3,
    max_budget: int | None = None,
) -> tuple[Node[AgentState[T]] | None, Node[AgentState[T]]]:
    span = langfuse.span(
        name="dfs",
        trace_id=langfuse_parent_trace_id,
        parent_observation_id=langfuse_parent_observation_id,
        input=init.__dict__, # check
    )
    root = Node(common.AgentState(init, None), id=span.id)
    expand_fn = langfuse_expand(context, llm_fn, langfuse, langfuse_parent_trace_id, span.id)
    solution = common.dfs_rewind(root, expand_fn, max_depth, max_width, max_budget)
    span.end(
        output=solution.data.inner.__dict__, # check
        metadata={"child_node_id": root._id}
    )
    return solution, root


def solve_agent[T](
    init: common.AgentMachine[T],
    context: T,
    trace_name: str,
    m_claude: AnthropicBedrock,
    langfuse: Langfuse,
):
    def llm_fn(
        messages: list[MessageParam],
        generation: StatefulGenerationClient,
    ) -> MessageParam:
        completion = span_claude_bedrock(m_claude, messages, generation)
        return MessageParam(role="assistant", content=completion.content)

    @observe(capture_input=False, capture_output=False, name=trace_name)
    def _inner():
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        langfuse_context.update_current_trace(name=trace_name)
        solution = agent_dfs(
            init,
            context,
            llm_fn,
            langfuse,
            trace_id,
            observation_id,
            max_depth=3,
            max_width=2,
        )
        return solution
    return _inner()


def run_sequence():
    langfuse_client = Langfuse()
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    m_claude = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")

    tsp_start = typespec.Entry("Generate a bot that stores and searches notes")
    tsp_result, _tsp_root = solve_agent(tsp_start, Context(compiler), "solve_typespec", m_claude, langfuse_client)
    assert tsp_result and isinstance(tsp_result.data.inner, typespec.Success), "typespec solution failed"

    dz_start = drizzle.Entry(tsp_result.data.inner.typespec)
    dz_result, _dz_root = solve_agent(dz_start, Context(compiler), "solve_drizzle", m_claude, langfuse_client)
    assert dz_result and isinstance(dz_result.data.inner, drizzle.Success), "drizzle solution failed"

    tsc_start = typescript.Entry(tsp_result.data.inner.typespec)
    tsc_result, _tsc_root = solve_agent(tsc_start, Context(compiler), "solve_typescript", m_claude, langfuse_client)
    assert tsc_result and isinstance(tsc_result.data.inner, typescript.Success), "solution failed"

    function = tsc_result.data.inner.functions[0]
    tests_start = handler_tests.Entry(function.name, tsc_result.data.inner.typescript_schema, dz_result.data.inner.drizzle_schema)
    tests_result, _tests_root = solve_agent(tests_start, Context(compiler), "solve_handler_tests", m_claude, langfuse_client)
    assert tests_result and isinstance(tests_result.data.inner, handler_tests.Success), "solution failed"

    function = tsc_result.data.inner.functions[0]
    handler_start = handlers.Entry(function.name, tsc_result.data.inner.typescript_schema, dz_result.data.inner.drizzle_schema, tests_result.data.inner.source)
    handler_result, _handler_root = solve_agent(handler_start, Context(compiler), "solve_handlers", m_claude, langfuse_client)
    assert handler_result and isinstance(handler_result.data.inner, handlers.Success), "solution failed"
