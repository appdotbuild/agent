import os
import anyio
import logging
import uuid
from typing import Dict, Any, List, TypedDict, NotRequired

from statemachine import StateMachine, State, Actor
from models.anthropic_bedrock import AnthropicBedrockLLM
from anthropic import AsyncAnthropicBedrock
from workspace import Workspace
from trpc_agent import DraftActor, HandlersActor, IndexActor, FrontendActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)


class ApplicationContext(TypedDict):
    """Context for the fullstack application state machine"""
    user_prompt: str
    server_files: NotRequired[Dict[str, str]]
    frontend_files: NotRequired[Dict[str, str]]
    error: NotRequired[str]


async def main():
    """Simple runnable example to demonstrate the application"""
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    for package in ['urllib3', 'httpx', 'google_genai.models']:
        logging.getLogger(package).setLevel(logging.WARNING)

    # Connect to dagger
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        # Import actors from trpc_agent

        # Set up workspaces
        workspace = await Workspace.create(
            base_image="oven/bun:1.2.5-alpine",
            context=dagger.dag.host().directory("./prefabs/trpc_fullstack"),
            setup_cmd=[["bun", "install"]],
        )
        backend_workspace = workspace.clone().cwd("/app/server")
        frontend_workspace = workspace.clone().cwd("/app/client")

        # Set up LLM client
        m_client = AnthropicBedrockLLM(AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2"))

        # Configure model parameters
        model_params = {
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "max_tokens": 8192,
        }

        # User prompt
        user_prompt = "Simple todo app"

        # Create actors
        draft_actor = DraftActor(m_client, backend_workspace.clone(), model_params)
        handlers_actor = HandlersActor(m_client, backend_workspace.clone(), model_params, beam_width=3)
        index_actor = IndexActor(m_client, backend_workspace.clone(), model_params, beam_width=3)
        front_actor = FrontendActor(m_client, frontend_workspace.clone(), model_params, beam_width=1, max_depth=20)

        # Create context and define state machine
        context: ApplicationContext = {"user_prompt": user_prompt}

        # Define actions to update context
        async def update_server_files(ctx: ApplicationContext, result: Any) -> None:
            """Update server files in context from actor result"""
            logger.info("Updating server files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        if "server_files" not in ctx:
                            ctx["server_files"] = {}
                        ctx["server_files"].update(node.data.files)

        async def update_frontend_files(ctx: ApplicationContext, result: Any) -> None:
            """Update frontend files in context from actor result"""
            logger.info("Updating frontend files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        ctx["frontend_files"] = node.data.files

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            logger.error(f"Setting error in context: {error}")
            ctx["error"] = str(error)

        # Define state machine states
        states: State[ApplicationContext] = {
            "states": {
                "draft": {
                    "invoke": {
                        "src": draft_actor,
                        "input_fn": lambda ctx: (ctx["user_prompt"],),
                        "on_done": {
                            "target": "handlers",
                            "actions": [update_server_files],
                        },
                        "on_error": {
                            "target": "failure",
                            "actions": [set_error],
                        },
                    }
                },
                "handlers": {
                    "invoke": {
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (ctx["server_files"],),
                        "on_done": {
                            "target": "index",
                            "actions": [update_server_files],
                        },
                        "on_error": {
                            "target": "failure",
                            "actions": [set_error],
                        },
                    }
                },
                "index": {
                    "invoke": {
                        "src": index_actor,
                        "input_fn": lambda ctx: (ctx["server_files"],),
                        "on_done": {
                            "target": "frontend",
                            "actions": [update_server_files],
                        },
                        "on_error": {
                            "target": "failure",
                            "actions": [set_error],
                        },
                    }
                },
                "frontend": {
                    "invoke": {
                        "src": front_actor,
                        "input_fn": lambda ctx: (ctx["user_prompt"], ctx["server_files"]),
                        "on_done": {
                            "target": "complete",
                            "actions": [update_frontend_files],
                        },
                        "on_error": {
                            "target": "failure",
                            "actions": [set_error],
                        },
                    }
                },
                "complete": {
                    # Terminal success state
                },
                "failure": {
                    # Terminal failure state
                }
            },
            "on": {
                "START": "draft"
            }
        }

        # Create and run state machine
        logger.info("Creating state machine")
        fsm = StateMachine[ApplicationContext](states, context)

        logger.info("Starting state machine execution")
        try:
            await fsm.send("START")
            logger.info(f"State machine finished at state: {fsm.stack_path}")

            # Print results
            if "error" in fsm.context:
                logger.error(f"Application run failed: {fsm.context['error']}")
            else:
                logger.info("Application run completed successfully")

                # Count files generated
                server_files = fsm.context.get("server_files", {})
                frontend_files = fsm.context.get("frontend_files", {})
                logger.info(f"Generated {len(server_files)} server files and {len(frontend_files)} frontend files")
        except Exception as e:
            logger.exception(f"Error running state machine: {e}")


if __name__ == "__main__":
    anyio.run(main)
