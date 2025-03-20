from experimental import IntegratedProcessor, TracingClient, Compiler, Processor
from typing import List, Tuple
import jinja2
from anthropic import AnthropicBedrock
from langfuse.decorators import langfuse_context
import logging
import coloredlogs
import sys
from anthropic.types import MessageParam


from fire import Fire

# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = logging.getLogger(__name__)



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


def main(initial_prompt: str = None):
    """
    Main entry point for the experimental module.
    Initializes an integrated handler with all tools and processes with Claude.
    """
    langfuse_context.configure(enabled=False)

    logger.info("[Main] Initializing components...")
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")

    # Create an integrated processor with access to all tools
    processor = IntegratedProcessor(
        tracing_client=TracingClient(client),
        compiler=Compiler("botbuild/tsp_compiler", "botbuild/app_schema"),
        jinja_env=jinja2.Environment()
    )
    logger.info("[Main] Components initialized successfully")

    # Example: Starting from scratch with an app description
    app_description = initial_prompt or """
        A workout tracking application that helps users log exercises, sets, reps, and weights.
        It should track progress over time and allow users to view their personal records.
        The app should support multiple workout routines and provide analytics on improvements.
    """

    # Set the app description in the context
    processor.context.set("app_description", app_description)

    logger.info("[Main] Sending request to Claude...")
    current_messages = [{
        "role": "user",
        "content": f"""You are a software engineering expert. Your goal is to generate a complete application starting from an application description:

        <app_description>
        {app_description}
        </app_description>
        """
    }]
    is_complete = False

    while True:
        current_messages, is_complete = run_with_claude(
            processor,
            client,
            current_messages
        )
        if is_complete:
            break
        else:
            logger.info(f"[Main] iteration: {len(current_messages) - 1}")

    # At this point, we have the complete generated code in the processor context
    logger.info("[Main] Generation completed successfully")
    typespec = processor.context.get("last_typespec")
    typescript = processor.context.get("last_typescript")
    drizzle_schema = processor.context.get("last_schema")

    logger.info(f"[Main] Generated TypeSpec: {len(typespec)} characters")
    logger.info(f"[Main] Generated TypeScript: {len(typescript)} characters")
    logger.info(f"[Main] Generated Drizzle schema: {len(drizzle_schema)} characters")


if __name__ == "__main__":
    Fire(main)
