from typing import Callable
from anthropic.types import MessageParam
from fsm_core.llm_common import AnthropicClient

from langfuse import Langfuse
from langfuse.client import StatefulGenerationClient
from langfuse.decorators import observe, langfuse_context

from . import common
from .common import AgentState, Node


def bedrock_claude(
    client: AnthropicClient,
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
    client: AnthropicClient,
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
        output=solution.data.inner.__dict__ if solution else None, # check
        metadata={"child_node_id": root._id}
    )
    return solution, root


def solve_agent[T](
    init: common.AgentMachine[T],
    context: T,
    trace_name: str,
    m_claude: AnthropicClient,
    langfuse: Langfuse,
    max_depth: int = 3,
    max_width: int = 2,
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
        assert trace_id and observation_id, "missing trace_id or observation_id"
        langfuse_context.update_current_trace(name=trace_name)
        solution = agent_dfs(
            init,
            context,
            llm_fn,
            langfuse,
            trace_id,
            observation_id,
            max_depth=max_depth,
            max_width=max_width,
        )
        return solution
    return _inner()
