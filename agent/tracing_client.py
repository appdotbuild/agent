from anthropic import AnthropicBedrock
from anthropic.types import Message, MessageParam
from langfuse.decorators import langfuse_context, observe


class TracingClient:
    def __init__(self, m_claude: AnthropicBedrock, thinking_budget: int = 0):
        self.m_claude = m_claude
        self.thinking_budget = thinking_budget
    
    @observe(as_type="generation", name="Anthropic-generation")
    def call_anthropic(
        self,
        messages: list[MessageParam],
        model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        max_tokens: int = 8192,
        temperature: float = 1.0,
        **kwargs,
    ):
        trace_messages = messages.copy()
        system_prompt = kwargs.pop("system", None)
        if system_prompt:
            trace_messages.append({"role": "system", "content": system_prompt})
        langfuse_context.update_current_observation(
            input=trace_messages,
            model=model,
            model_parameters={
                "maxTokens": max_tokens,
                "temperature": temperature,
                "thinkingBudget": self.thinking_budget,
            },
            metadata=kwargs,
        )
        if self.thinking_budget > 0:
            thinking_config = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget,
            }
        else:
            thinking_config = {
                "type": "disabled",
            }
        completion: Message = self.m_claude.messages.create(
            max_tokens=max_tokens + self.thinking_budget,
            model=model,
            messages=messages,
            temperature=temperature,
            thinking=thinking_config,
            **kwargs,
        )
        if len(completion.content) == 1 and completion.content[0].type == "text":
            trace_output = completion.content[0].text
        else:
            trace_output = completion.content
        langfuse_context.update_current_observation(
            output=trace_output,
            usage={
                "input": completion.usage.input_tokens,
                "output": completion.usage.output_tokens,
            }
        )
        return completion
