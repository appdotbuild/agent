from mcp.server.fastmcp import FastMCP
from jinja2 import Environment

from anthropic import AnthropicBedrock
from policies.experimental import IntegratedProcessor
from tracing_client import TracingClient
from compiler.core import Compiler
from application import langfuse_context
import logging
import coloredlogs
import sys

# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = logging.getLogger(__name__)

# Create an MCP server
mcp = FastMCP("AppBuild", port=7758)  # Use a specific port to avoid conflicts, but any port can be used because the transport is stdio
langfuse_context.configure(enabled=False)

client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
processor = IntegratedProcessor(
    tracing_client=TracingClient(client),
    compiler=Compiler("botbuild/tsp_compiler", "botbuild/app_schema"),
    jinja_env=Environment()
)

tools_description = processor.get_tool_definitions()
tools_fns = processor.get_tool_mapping()

# Add wrapper function to log all parameters
def create_debug_wrapper(fn, tool_name):
    def wrapper(**kwargs):
        # Handle case where parameters are incorrectly nested under a 'kwargs' key
        actual_params = kwargs.get('kwargs', kwargs)
        logger.info(f"[DEBUG] Calling {tool_name} with parameters: {actual_params}")
        try:
            result = fn(**actual_params)
            logger.info(f"[DEBUG] {tool_name} returned successfully")
            return result
        except Exception as e:
            logger.exception(f"[DEBUG] Error in {tool_name}: {str(e)}")
            return {"incorrect tool call": str(e)}
    return wrapper

for tool_name, tool_fn in tools_fns.items():
    tool, = [x for x in tools_description if x["name"] == tool_name ]
    desc = tool["description"]
    schema = tool["input_schema"]
    # simplified view of the schema for the main agent
    schema.pop("type", None)
    desc += f"\nInput schema: {schema}"
    logger.info(f"Adding tool {tool_name} with description: {desc}")
    wrapped_fn = create_debug_wrapper(tool_fn, tool_name)
    mcp.add_tool(wrapped_fn, name=tool_name, description=desc)

if __name__ == "__main__":
    print("Starting MCP server", file=sys.stderr)
    mcp.run(transport="stdio")
