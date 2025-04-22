import json
import anyio
import os
import traceback
import subprocess
import tempfile
from typing import List, Optional
from log import get_logger
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.models import AgentSseEvent
from datetime import datetime

logger = get_logger(__name__)


async def run_chatbot_client(host: str, port: int, state_file: str, settings: Optional[str] = None, autosave=False) -> None:
    """
    Async interactive Agent CLI chat.
    """

    # Prepare state and settings
    state_file = os.path.expanduser(state_file)
    previous_events: List[AgentSseEvent] = []
    previous_messages: List[str] = []
    request = None

    # Parse settings if provided
    settings_dict = {}
    if settings:
        try:
            settings_dict = json.loads(settings)
        except json.JSONDecodeError:
            print(f"Warning: could not parse settings JSON: {settings}")

    # Load saved state if available
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                saved = json.load(f)
                previous_events = []
                for e in saved.get("events", []):
                    try:
                        previous_events.append(AgentSseEvent.model_validate(e))
                    except Exception as err:
                        logger.warning(f"Skipping invalid saved event: {err}")
                previous_messages = saved.get("messages", [])
                print(f"Loaded conversation with {len(previous_messages)} messages")
        except Exception as e:
            print(f"Warning: could not load state: {e}")

    # Banner
    divider = "=" * 60
    print(divider)
    print("Interactive Agent CLI Chat")
    print("Type '/help' for commands.")
    print(divider)

    if host:
        base_url = f"http://{host}:{port}"
        print(f"Connected to {base_url}")
    else:
        base_url = None # Use ASGI transport for local testing
    async with AgentApiClient(base_url=base_url) as client:
        while True:
            try:
                ui = input("\033[94mYou> \033[0m")
                if ui.startswith("+"):
                    ui = "A simple greeting app that says hello in five languages and stores history of greetings"
            except (EOFError, KeyboardInterrupt):
                print("\nExiting…")
                return

            cmd = ui.strip()
            if not cmd:
                continue
            action, *rest = cmd.split(None, 1)
            match action.lower():
                case "/exit" | "/quit":
                    print("Goodbye!")
                    return
                case "/help":
                    print(
                        "Commands:\n"
                        "/help       Show this help\n"
                        "/exit, /quit Exit chat\n"
                        "/clear      Clear conversation\n"
                        "/save       Save state to file"
                        "\n"
                        "/diff       Show the latest unified diff\n"
                        "/apply      Apply the latest diff to the current directory\n"
                        "/export     Export the latest diff to a patchfile"
                    )
                    continue
                case "/clear":
                    previous_events.clear()
                    previous_messages.clear()
                    request = None
                    print("Conversation cleared.")
                    continue
                case "/save":
                    with open(state_file, "w") as f:
                        json.dump({
                            "events": [e.model_dump() for e in previous_events],
                            "messages": previous_messages,
                            "agent_state": request.agent_state if request else None,
                            "timestamp": datetime.now().isoformat()
                        }, f, indent=2)
                    print(f"State saved to {state_file}")
                    continue
                case "/diff":
                    diff = latest_unified_diff()
                    if diff:
                        print(diff)
                    else:
                        print("No diff available")
                    continue
                case "/apply":
                    diff = latest_unified_diff()
                    if not diff:
                        print("No diff available to apply")
                        continue
                    try:
                        with tempfile.NamedTemporaryFile(suffix='.patch', delete=False) as tmp:
                            tmp.write(diff.encode('utf-8'))
                            tmp_path = tmp.name
                        result = subprocess.run(
                            ['git', 'apply', tmp_path],
                            capture_output=True,
                            text=True
                        )
                        os.unlink(tmp_path)
                        if result.returncode == 0:
                            print("Successfully applied the diff to the current directory")
                        else:
                            print(f"Failed to apply diff: {result.stderr}")
                    except Exception as e:
                        print(f"Error applying diff: {e}")
                    continue
                case "/export":
                    diff = latest_unified_diff()
                    if not diff:
                        print("No diff available to export")
                        continue
                    try:
                        patch_file = "agent_diff.patch"
                        with open(patch_file, "w") as f:
                            f.write(diff)
                        print(f"Successfully exported diff to {patch_file}")
                    except Exception as e:
                        print(f"Error exporting diff: {e}")
                    continue
                case _:
                    content = cmd

            # Send or continue conversation
            try:
                print("\033[92mBot> \033[0m", end="", flush=True)
                auth_token = os.environ.get("BUILDER_TOKEN")
                if request is None:
                    logger.warning("Sending new message")
                    events, request = await client.send_message(content, settings=settings_dict, auth_token=auth_token)
                else:
                    logger.warning("Sending continuation")
                    events, request = await client.continue_conversation(previous_events, request, content)

                for evt in events:
                    if evt.message and evt.message.content:
                        print(evt.message.content, end="", flush=True)
                print()

                previous_messages.append(content)
                previous_events.extend(events)

                if autosave:
                    with open(state_file, "w") as f:
                        json.dump({
                            "events": [e.model_dump() for e in previous_events],
                            "messages": previous_messages,
                            "agent_state": request.agent_state,
                            "timestamp": datetime.now().isoformat()
                        }, f, indent=2)
            except Exception as e:
                print(f"Error: {e}")
                traceback.print_exc()

    # Helper to fetch the most recent unified diff from collected events
    def latest_unified_diff() -> Optional[str]:
        """Return the most recent unified diff found in previous_events, if any."""
        for evt in reversed(previous_events):
            try:
                diff_val = evt.message.unified_diff  # type: ignore[attr-defined]
                if diff_val:
                    return diff_val
            except AttributeError:
                # Event message may not have unified_diff
                continue
        return None

def cli(host: str = "",
        port: int = 8001,
        state_file: str = "/tmp/agent_chat_state.json",
        ):
    anyio.run(run_chatbot_client, host, port, state_file, backend="asyncio")

if __name__ == "__main__":
    from fire import Fire
    Fire(cli)
