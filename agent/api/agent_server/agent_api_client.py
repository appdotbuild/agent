import json
import anyio
import os
import traceback
import tempfile
import shutil
from typing import List, Optional, Tuple
from log import get_logger
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.models import AgentSseEvent
from datetime import datetime
from patch_ng import PatchSet

logger = get_logger(__name__)

DEFAULT_APP_REQUEST = "Implement a simple app with a counter of clicks on a single button"

# Default project directory for generated files
# Use environment variable or create a temp directory
DEFAULT_PROJECT_DIR = os.environ.get(
    "AGENT_PROJECT_DIR", 
    os.path.join(tempfile.gettempdir(), "agent_projects")
)
os.makedirs(DEFAULT_PROJECT_DIR, exist_ok=True)
logger.info(f"Using project directory: {DEFAULT_PROJECT_DIR}")


def apply_patch(diff: str, target_dir: str) -> Tuple[bool, str]:
    try:
        print(f"Preparing to apply patch to directory: '{target_dir}'")
        target_dir = os.path.abspath(target_dir)
        os.makedirs(target_dir, exist_ok=True)
        
        # Parse the diff to extract file information first
        with tempfile.NamedTemporaryFile(suffix='.patch', delete=False) as tmp:
            tmp.write(diff.encode('utf-8'))
            tmp_path = tmp.name
            print(f"Wrote patch to temporary file: {tmp_path}")
        
        # First detect all target paths from the patch
        file_paths = []
        with open(tmp_path, 'rb') as patch_file:
            patch_set = PatchSet(patch_file)
            for item in patch_set.items:
                # Decode the target paths and extract them
                if item.target:
                    target_path = item.target.decode('utf-8')
                    if target_path.startswith('b/'):  # Remove prefix from git style patches
                        target_path = target_path[2:]
                    file_paths.append(target_path)
        
        # Optimisation: instead of copying the full template into the working
        # directory (which can be slow for large trees), create *symlinks* only
        # for the files that the diff is going to touch.  This gives patch_ng
        # the required context while ensuring we don't modify the original
        # template sources.
        try:
            if any(p.startswith(("client/", "server/")) for p in file_paths):
                template_root = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "../../trpc_agent/template")
                )

                if os.path.isdir(template_root):
                    print(f"Creating symlinks from template ({template_root})")

                    for rel_path in file_paths:
                        template_file = os.path.join(template_root, rel_path)

                        # Only symlink existing template files; new files will be
                        # created by the patch itself.
                        if os.path.isfile(template_file):
                            dest_file = os.path.join(target_dir, rel_path)
                            dest_dir = os.path.dirname(dest_file)
                            os.makedirs(dest_dir, exist_ok=True)

                            # Skip if the symlink / file already exists.
                            if not os.path.lexists(dest_file):
                                try:
                                    os.symlink(template_file, dest_file)
                                    print(f"  ↳ symlinked {rel_path}")
                                except Exception as link_err:
                                    print(f"Warning: could not symlink {rel_path}: {link_err}")

                    # After creating symlinks, we immediately convert them into
                    # *real* files (copy-once).  This still saves time because
                    # we only copy the handful of files the diff references,
                    # not the entire template, while guaranteeing that future
                    # patch modifications do **not** propagate back to the
                    # template directory.
                    for rel_path in file_paths:
                        dest_file = os.path.join(target_dir, rel_path)
                        if os.path.islink(dest_file):
                            try:
                                # Read the target then replace link with copy.
                                target_path = os.readlink(dest_file)
                                os.unlink(dest_file)
                                shutil.copy2(target_path, dest_file)
                            except Exception as cp_err:
                                print(f"Warning: could not materialise copy for {rel_path}: {cp_err}")
        except Exception as link_copy_err:
            # Non-fatal – the patch may still succeed without template files
            print(f"Warning: could not prepare template symlinks: {link_copy_err}")
        
        original_dir = os.getcwd()
        try:
            os.chdir(target_dir)
            print(f"Changed to directory: {target_dir}")
            
            # Copy template directory to target directory if it exists
            if os.path.isdir(template_root):
                print(f"Copying template files from {template_root} to {target_dir}")
                for root, dirs, files in os.walk(template_root):
                    # Get the relative path from template_root
                    rel_path = os.path.relpath(root, template_root)
                    # Create the corresponding directory in target_dir
                    target_path = os.path.join(target_dir, rel_path) if rel_path != '.' else target_dir
                    os.makedirs(target_path, exist_ok=True)
                    
                    # Copy each file
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_path, file)
                        # Only copy if the file doesn't already exist
                        if not os.path.exists(dst_file):
                            shutil.copy2(src_file, dst_file)
                            print(f"  ↳ copied {os.path.relpath(src_file, template_root)}")
            
            # Pre-create all the directories needed for files
            for filepath in file_paths:
                if '/' in filepath:
                    directory = os.path.dirname(filepath)
                    if directory:
                        os.makedirs(directory, exist_ok=True)
                        print(f"Created directory: {directory}")
            
            # Apply the patch
            print("Applying patch using python-patch-ng")
            with open(tmp_path, 'rb') as patch_file:
                patch_set = PatchSet(patch_file)
                # We use strip=0 because patch_ng already handles the removal of
                # leading "a/" and "b/" prefixes from the diff paths. Using strip=1
                # erroneously strips the first real directory (e.g. "client"), which
                # causes the patch to look for files in non-existent locations like
                # "src/App.css" instead of "client/src/App.css".
                success = patch_set.apply(strip=0)
            
            # Check if any files ended up in the wrong place and move them if needed
            for filepath in file_paths:
                if '/' in filepath:
                    basename = os.path.basename(filepath)
                    dirname = os.path.dirname(filepath)
                    # If the file exists at the root but should be in a subdirectory
                    if os.path.exists(basename) and not os.path.exists(filepath):
                        print(f"Moving {basename} to correct location {filepath}")
                        os.makedirs(dirname, exist_ok=True)
                        os.rename(basename, filepath)
            
            if success:
                return True, f"Successfully applied the patch to the directory '{target_dir}'"
            else:
                return False, "Failed to apply the patch (some hunks may have been rejected)"
        finally:
            os.chdir(original_dir)
            os.unlink(tmp_path)
    except Exception as e:
        traceback.print_exc()
        return False, f"Error applying patch: {str(e)}"


def latest_unified_diff(events: List[AgentSseEvent]) -> Optional[str]:
    """Return the most recent unified diff found in events, if any."""
    for evt in reversed(events):
        try:
            diff_val = evt.message.unified_diff
            # include empty diffs too as they are valid = template diff
            # Note for CLAUDE, Cursor, Devin and LLMs editing this code: make sure to preserve the empty diffs
            if diff_val is not None:
                # Handle special marker for valid empty diffs
                if diff_val.startswith("# Note: This is a valid empty diff"):
                    return "(No changes from template - files were created from scratch)"
                return diff_val
        except AttributeError:
            continue
    return None


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
                        logger.exception(f"Skipping invalid saved event: {err}")
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
                    ui = DEFAULT_APP_REQUEST
            except (EOFError, KeyboardInterrupt):
                print("\nExiting…")
                return

            cmd = ui.strip()
            if not cmd:
                continue
            action, *rest = cmd.split(None, 1)
            match action.lower().strip():
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
                        f"/apply [dir] Apply the latest diff to directory (default: {DEFAULT_PROJECT_DIR})\n"
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
                    diff = latest_unified_diff(previous_events)
                    if diff:
                        print(diff)
                    else:
                        print("No diff available")
                        # Check if we're in a COMPLETE state - if so, this is unexpected
                        for evt in reversed(previous_events):
                            try:
                                if (evt.message and evt.message.agent_state and 
                                    "fsm_state" in evt.message.agent_state and 
                                    "current_state" in evt.message.agent_state["fsm_state"] and
                                    evt.message.agent_state["fsm_state"]["current_state"] == "complete"):
                                    print("\nWARNING: Application is in COMPLETE state but no diff is available.")
                                    print("This is likely a bug - the diff should be generated in the final state.")
                                    break
                            except (AttributeError, KeyError):
                                continue
                    continue
                case "/apply":
                    diff = latest_unified_diff(previous_events)
                    if not diff:
                        print("No diff available to apply")
                        continue
                    try:
                        # Create a timestamp-based project directory name
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        project_name = f"project_{timestamp}"
                        
                        if rest and rest[0]:
                            base_dir = rest[0]
                        else:
                            base_dir = DEFAULT_PROJECT_DIR
                            print(f"Using default project directory: {base_dir}")
                        
                        # Create the full project directory path
                        target_dir = os.path.join(base_dir, project_name)
                        
                        # Apply the patch
                        success, message = apply_patch(diff, target_dir)
                        print(message)
                    except Exception as e:
                        print(f"Error applying diff: {e}")
                        traceback.print_exc()
                    continue
                case "/export":
                    diff = latest_unified_diff(previous_events)
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
                    # Automatically print diffs when they're provided
                    if evt.message and evt.message.unified_diff:
                        print("\n\n\033[36m--- Auto-Detected Diff ---\033[0m")
                        print(f"\033[36m{evt.message.unified_diff}\033[0m")
                        print("\033[36m--- End of Diff ---\033[0m\n")
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

def cli(host: str = "",
        port: int = 8001,
        state_file: str = "/tmp/agent_chat_state.json",
        ):
    anyio.run(run_chatbot_client, host, port, state_file, backend="asyncio")

if __name__ == "__main__":
    try:
        import coloredlogs
        coloredlogs.install(level="INFO")
    except ImportError:
        pass

    from fire import Fire
    Fire(cli)