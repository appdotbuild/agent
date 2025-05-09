import json
import anyio
import os
import traceback
import tempfile
import shutil
import subprocess
import readline
import atexit
from typing import List, Optional, Tuple
from log import get_logger
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.models import AgentSseEvent
from datetime import datetime
from patch_ng import PatchSet
import contextlib
from api.docker_utils import setup_docker_env, start_docker_compose, stop_docker_compose

logger = get_logger(__name__)

DEFAULT_APP_REQUEST = "Implement a simple app with a counter of clicks on a single button"

@contextlib.contextmanager
def project_dir_context():
    project_dir = os.environ.get("AGENT_PROJECT_DIR")
    is_temp = False

    if project_dir:
        project_dir = os.path.abspath(project_dir)
        os.makedirs(project_dir, exist_ok=True)
        logger.info(f"Using AGENT_PROJECT_DIR from environment: {project_dir}")
    else:
        project_dir = tempfile.mkdtemp(prefix="agent_project_")
        is_temp = True
        logger.info(f"Using temporary project directory: {project_dir}")

    try:
        yield project_dir
    finally:
        if is_temp and os.path.exists(project_dir):
            shutil.rmtree(project_dir)



current_server_process = None

HISTORY_FILE = os.path.expanduser("~/.agent_chat_history")
HISTORY_SIZE = 1000  # Maximum number of history entries to save

def setup_readline():
    """Configure readline for command history"""
    try:
        if not os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'w') as _:
                pass

        readline.read_history_file(HISTORY_FILE)
        readline.set_history_length(HISTORY_SIZE)

        import atexit
        atexit.register(readline.write_history_file, HISTORY_FILE)

        return True
    except Exception as e:
        print(f"Warning: Could not configure readline history: {e}")
        return False

def apply_patch(diff: str, target_dir: str) -> Tuple[bool, str]:
    try:
        print(f"Preparing to apply patch to directory: '{target_dir}'")
        target_dir = os.path.abspath(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        # Parse the diff to extract file information first
        with tempfile.NamedTemporaryFile(suffix='.patch', delete=False) as tmp:
            tmp.write(diff.encode('utf-8'))
            tmp_path = tmp.name
            print(f"\033[33mPatch file for apply operation created at: {os.path.abspath(tmp_path)}\033[0m")

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

                    # Copy all template files except specific excluded directories and hidden files
                    excluded_dirs = ["node_modules", "dist"]

                    def copy_template_files(base_dir, target_base):
                        """
                        Copy all template files recursively, except those in excluded directories
                        and hidden files (starting with a dot).
                        """
                        for root, dirs, files in os.walk(base_dir):
                            # Remove excluded directories and hidden directories from dirs to prevent recursion into them
                            dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith('.')]

                            # Get relative path from template root
                            rel_path = os.path.relpath(root, base_dir)
                            if rel_path == ".":
                                rel_path = ""

                            for file in files:
                                # Skip hidden files
                                if file.startswith('.') or file.endswith('.md'):
                                    continue

                                src_file = os.path.join(root, file)
                                # Create relative path within target directory
                                rel_file_path = os.path.join(rel_path, file)
                                dest_file = os.path.join(target_base, rel_file_path)
                                dest_dir = os.path.dirname(dest_file)

                                os.makedirs(dest_dir, exist_ok=True)
                                if not os.path.lexists(dest_file):
                                    try:
                                        # Directly copy the file (no symlink)
                                        shutil.copy2(src_file, dest_file)
                                        print(f"  ↳ copied file {rel_file_path}")
                                    except Exception as cp_err:
                                        print(f"Could not copy file {rel_file_path}: {cp_err}")

                    # Copy all template files recursively (except excluded dirs)
                    copy_template_files(template_root, target_dir)

                    # Then handle the files from the diff patch
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
                                    print(f"Could not symlink {rel_path}: {link_err}")

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
                                print(f"Could not materialise copy for {rel_path}: {cp_err}")
        except Exception as link_copy_err:
            # Non-fatal – the patch may still succeed without template files
            print(f"Could not prepare template symlinks: {link_copy_err}")

        original_dir = os.getcwd()
        try:
            os.chdir(target_dir)
            print(f"Changed to directory: {target_dir}")

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


def get_multiline_input(prompt: str) -> str:
    """
    Get multi-line input from the user.
    Input is terminated when the user enters an empty line.
    Command inputs (starting with '/' or '+') are processed immediately without requiring empty line.
    Supports up/down arrow keys for navigating through command history.
    """
    print(prompt, end="", flush=True)

    try:
        first_line = input()

        # Add non-empty, non-command inputs to history
        if first_line.strip() and not first_line.strip().startswith('/'):
            # Add to readline history if not already the last item
            if readline.get_current_history_length() == 0 or readline.get_history_item(readline.get_current_history_length()) != first_line:
                readline.add_history(first_line)

        # If it's a command (starts with '/' or '+'), return it immediately
        if first_line.strip().startswith('/') or first_line.strip().startswith('+'):
            return first_line

        lines = [first_line]

    except (EOFError, KeyboardInterrupt):
        print("\nInput terminated.")
        return ""

    # Continue collecting lines for multi-line input
    while True:
        try:
            # Show continuation prompt for subsequent lines
            print("\033[94m... \033[0m", end="", flush=True)
            line = input()

            if not line.strip():  # Empty line terminates input
                if not lines or (len(lines) == 1 and not lines[0].strip()):  # Don't allow empty input
                    continue
                break

            lines.append(line)
        except (EOFError, KeyboardInterrupt):
            print("\nInput terminated.")
            break

    full_input = "\n".join(lines)

    if len(lines) > 1:
        readline.add_history(full_input.replace('\n', ' '))

    return full_input


def apply_latest_diff(events: List[AgentSseEvent], resolved_target_dir: str) -> Tuple[bool, str, Optional[str]]:
    """
    Apply the latest diff to the specified resolved directory.
    The caller is responsible for determining and confirming this directory.

    Args:
        events: List of AgentSseEvent objects
        resolved_target_dir: The absolute path to the directory where the patch should be applied.

    Returns:
        Tuple containing:
            - Success status (boolean)
            - Result message (string)
            - Target directory where diff was applied (string, or None if failed)
    """
    diff = latest_unified_diff(events)
    if not diff:
        return False, "No diff available to apply", None

    try:
        print(f"Applying diff to confirmed target directory: {resolved_target_dir}")
        
        success, message = apply_patch(diff, resolved_target_dir)

        if success:
            return True, message, resolved_target_dir
        else:
            return False, message, resolved_target_dir # Return dir even on partial failure for context

    except Exception as e:
        error_msg = f"Error applying diff: {e}"
        traceback.print_exc()
        return False, error_msg, None


docker_cleanup_dirs = []


def cleanup_docker_projects():
    """Clean up any Docker projects that weren't properly shut down"""
    global docker_cleanup_dirs

    for project_dir in docker_cleanup_dirs:
        if os.path.exists(project_dir):
            print(f"Cleaning up Docker resources in {project_dir}")
            try:
                stop_docker_compose(project_dir, None)  # No project name, will use directory name
            except Exception as e:
                print(f"Error during cleanup of {project_dir}: {e}")

atexit.register(cleanup_docker_projects)

async def run_chatbot_client(host: str, port: int, state_file: str, settings: Optional[str] = None, autosave=False) -> None:
    """
    Async interactive Agent CLI chat.
    """
    # Make server process accessible globally
    global current_server_process

    # Prepare state and settings
    state_file = os.path.expanduser(state_file)
    previous_events: List[AgentSseEvent] = []
    previous_messages: List[str] = []
    request = None

    history_enabled = setup_readline()

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
    print("Use an empty line to finish multi-line input.")
    if history_enabled:
        print("Use up/down arrow keys to navigate through command history.")
    print(divider)

    if host:
        base_url = f"http://{host}:{port}"
        print(f"Connected to {base_url}")
    else:
        base_url = None # Use ASGI transport for local testing

    # Track how many messages from the agent chat history we've already displayed
    displayed_message_count = 0
    last_event_time = None # Initialize to None

    def print_event(event: AgentSseEvent) -> None:
        """Pretty-print incoming SSE events, only showing new chat messages.

        – Detects when the assistant returns the entire chat history as a JSON list
          of messages and prints only those that have not been shown yet.
        – Large JSON/text payloads (>500 chars) are written to a temp file instead
          of being dumped in the console.
        – Diffs are always saved to a temp .patch file with the path printed.
        – App name / commit message banners are printed when first encountered.
        """
        nonlocal displayed_message_count, last_event_time
        current_time = datetime.now()

        # ANSI escape codes for colors - MOVED TO THE TOP
        C_BLUE = '\033[94m'
        C_GREEN = '\033[92m'
        C_YELLOW = '\033[93m'
        C_RED = '\033[91m'
        C_MAGENTA = '\033[95m'
        C_CYAN = '\033[96m'
        C_GREY = '\033[90m' # Added grey for timings
        C_END = '\033[0m'
        C_BOLD = '\033[1m'

        # Add a newline before each event's output for separation
        print() 

        if last_event_time:
            duration = current_time - last_event_time
            duration_seconds = duration.total_seconds()
            print(f"{C_GREY}(... processed in {duration_seconds:.2f} seconds ...){C_END}")
            print() # Extra newline after timing for better separation
        
        last_event_time = current_time # Update for the next event

        msg = event.message
        if not msg:
            return

        # 1. Handle diff payloads --------------------------------------------------
        if msg.unified_diff:
            try:
                with tempfile.NamedTemporaryFile(suffix="_received.patch", delete=False, mode="w", encoding="utf-8") as tmp:
                    tmp.write(msg.unified_diff)
                    patch_path = tmp.name
                print(f"{C_CYAN}[diff] saved: {os.path.abspath(patch_path)}{C_END}")
            except Exception as err:
                print(f"{C_RED}[diff] error saving: {err}{C_END}")

        # 2. Handle content ---------------------------------------------------------
        if msg.content:
            content_raw = msg.content  # May be str or other type
            # a) Chat-history JSON array (string) -----------------------------------
            if isinstance(content_raw, str) and content_raw.lstrip().startswith('['):
                try:
                    history = json.loads(content_raw)
                except json.JSONDecodeError:
                    history = None

                if isinstance(history, list) and all(isinstance(m, dict) for m in history):
                    new_messages = history[displayed_message_count:]
                    if new_messages:
                        for m_item in new_messages:  # Renamed 'm' to 'm_item' to avoid conflict
                            role = m_item.get("role", "unknown")
                            role_color = C_BLUE if role == "assistant" else C_YELLOW
                            prefix = f"{role_color}[{role}]{C_END}" 
                            print(prefix, end=" ") 
                            for item in m_item.get("content", []):
                                if isinstance(item, dict):
                                    t = item.get("type")
                                    if t == "text":
                                        print(item.get('text', '').strip(), end=" ") 
                                    elif t in ("tool_use", "tool_use_result"):
                                        print(f"{C_MAGENTA}[{t}:{item.get('name','')}] {C_END}", end=" ")
                            print() 
                        displayed_message_count = len(history)
                    return 
            # b) Generic content (possibly big JSON) --------------------------------
            content_str = str(content_raw)
            if content_str.lstrip().startswith(('{', '[')) and len(content_str) > 500:
                try:
                    with tempfile.NamedTemporaryFile(suffix="_content.json", delete=False, mode="w", encoding="utf-8") as tmp:
                        tmp.write(content_str)
                        path = tmp.name
                    print(f"{C_GREEN}[content] {len(content_str)} bytes saved to {os.path.abspath(path)}{C_END}")
                except Exception as err:
                    print(f"{C_RED}[content] error saving large payload: {err}{C_END}")
            else:
                print(content_str, end="", flush=True)
                # Add a newline if it was just plain text to separate from potential metadata below
                if not (msg.app_name or msg.commit_message or msg.unified_diff):
                    print()

        # 3. Extra metadata ---------------------------------------------------------
        if msg.app_name:
            print(f"{C_BOLD}{C_GREEN}🚀 [app] {msg.app_name}{C_END}")
        if msg.commit_message:
            print(f"{C_BOLD}{C_GREEN}📝 [commit] {msg.commit_message}{C_END}")

    async with AgentApiClient(base_url=base_url) as client:
        with project_dir_context() as project_dir:
            while True:
                try:
                    ui = get_multiline_input("\033[94mYou> \033[0m")
                    if ui.startswith("+"):
                        ui = DEFAULT_APP_REQUEST
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting…")
                    return

                cmd = ui.strip()
                if not cmd:
                    continue

                first_line = cmd.split('\n', 1)[0].strip()
                if first_line.startswith('/'):
                    action, *rest = first_line.split(None, 1)
                    cmd = first_line
                else:
                    action = None

                match action.lower().strip() if action else None:
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
                            f"/apply [dir] Apply the latest diff to directory (default: {project_dir})\n"
                            "/export     Export the latest diff to a patchfile\n"
                            "/run [dir]  Apply diff, install deps, and start dev server\n"
                            "/stop       Stop the currently running server\n"
                            "/info       Show the app name and commit message"
                        )
                        continue
                    case "/clear":
                        previous_events.clear()
                        previous_messages.clear()
                        request = None
                        print("Conversation cleared.")
                        continue
                    case "/info":
                        app_name = None
                        commit_message = None
                        
                        # Look for app_name and commit_message in the events
                        for evt in reversed(previous_events):
                            try:
                                if evt.message:
                                    if app_name is None and evt.message.app_name is not None:
                                        app_name = evt.message.app_name
                                    if commit_message is None and evt.message.commit_message is not None:
                                        commit_message = evt.message.commit_message
                                    if app_name is not None and commit_message is not None:
                                        break
                            except AttributeError:
                                continue
                        
                        if app_name:
                            print(f"\033[35m🚀 App Name: {app_name}\033[0m")
                        else:
                            print("\033[33mNo app name available\033[0m")
                            
                        if commit_message:
                            print(f"\033[35m📝 Commit Message: {commit_message}\033[0m")
                        else:
                            print("\033[33mNo commit message available\033[0m")
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
                            if rest and rest[0]:
                                target_dir_to_check = os.path.abspath(rest[0])
                                print(f"User specified directory: {target_dir_to_check}")
                            else:
                                target_dir_to_check = project_dir # Use the session's project_dir
                                print(f"Using session default project directory: {target_dir_to_check}")

                            # Check if target directory exists and is not empty
                            if os.path.isdir(target_dir_to_check) and os.listdir(target_dir_to_check):
                                print(f"Warning: Directory '{target_dir_to_check}' is not empty.")
                                confirmation = get_multiline_input("Apply changes and overwrite existing files? (yes/no): ").strip().lower()
                                if confirmation != "yes":
                                    print("Operation cancelled by user.")
                                    continue
                            
                            # Ensure target directory exists (it might be a new one if user specified a non-existent path)
                            os.makedirs(target_dir_to_check, exist_ok=True)

                            # Apply the patch
                            success, message = apply_patch(diff, target_dir_to_check)
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
                    case "/run":
                        # First, stop any running server
                        if current_server_process and current_server_process.poll() is None:
                            print("Stopping currently running server...")
                            try:
                                current_server_process.terminate()
                                current_server_process.wait(timeout=5)
                            except Exception as e:
                                print(f"Warning: Error stopping previous server: {e}")
                                try:
                                    current_server_process.kill()
                                except (ProcessLookupError, OSError):
                                    pass
                            current_server_process = None

                        # Determine target directory for /run
                        if rest and rest[0]:
                            target_dir_for_run = os.path.abspath(rest[0])
                            print(f"User specified directory for run: {target_dir_for_run}")
                        else:
                            target_dir_for_run = project_dir # Use the session's project_dir
                            print(f"Using session default project directory for run: {target_dir_for_run}")

                        # Check if target directory exists and is not empty
                        if os.path.isdir(target_dir_for_run) and os.listdir(target_dir_for_run):
                            print(f"Warning: Directory '{target_dir_for_run}' is not empty.")
                            confirmation = get_multiline_input("Apply changes, overwrite, and run? (yes/no): ").strip().lower()
                            if confirmation != "yes":
                                print("Run operation cancelled by user.")
                                continue
                        
                        # Ensure target directory exists (it might be a new one if user specified a non-existent path)
                        # apply_latest_diff -> apply_patch will handle creation if it's a new path.
                        # For existing non-empty path, user has confirmed.
                        # For new path or empty existing path, no confirmation was needed.
                        
                        # Apply the diff to create/update the project
                        success, message, applied_target_dir = apply_latest_diff(previous_events, target_dir_for_run)
                        print(message)

                        if success and applied_target_dir:
                            print(f"\nSetting up project in {applied_target_dir}...")

                            # Setup docker environment with random container names
                            container_names = setup_docker_env()

                            # Add to cleanup list
                            if applied_target_dir not in docker_cleanup_dirs:
                                docker_cleanup_dirs.append(applied_target_dir)

                            print("Building services with Docker Compose...")
                            try:
                                # Start the services (with build)
                                success, error_message = start_docker_compose(
                                    applied_target_dir,
                                    container_names["project_name"],
                                    build=True
                                )

                                if not success:
                                    print("Warning: Docker Compose returned an error")
                                    print(f"Error output: {error_message}")
                                else:
                                    print("All services started successfully.")

                                    # Simple message about web access
                                    print("\n🌐 Web UI is available at:")
                                    print("   http://localhost:80 (for web servers, default HTTP port)")

                                    # Use Popen to follow the logs
                                    current_server_process = subprocess.Popen(
                                        ["docker", "compose", "logs", "-f"],
                                        cwd=applied_target_dir,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True
                                    )

                                    # Wait briefly and then print a few lines of output
                                    print("\nServer starting, initial output:")
                                    for _ in range(10):  # Print up to 10 lines of output
                                        line = current_server_process.stdout.readline()
                                        if not line:
                                            break
                                        print(f"  {line.rstrip()}")

                                    print(f"\nServer running in {applied_target_dir}")
                                    print("Use /stop command to stop the server when done.")

                            except subprocess.CalledProcessError as e:
                                print(f"Error during project setup: {e}")
                            except FileNotFoundError:
                                print("Error: 'docker' command not found. Please make sure Docker is installed.")
                        continue
                    case "/stop":
                        if not current_server_process:
                            print("No server is currently running.")
                            continue

                        if current_server_process.poll() is not None:
                            print("Server has already terminated.")
                            current_server_process = None
                            continue

                        # Get the directory where the server is running
                        server_dir = None
                        for dir_path in docker_cleanup_dirs:
                            try:
                                # Check if this matches the current_server_process working directory
                                if os.path.exists(dir_path) and current_server_process:
                                    server_dir = dir_path
                                    break
                            except (FileNotFoundError, PermissionError, OSError) as e:
                                logger.debug(f"Error checking directory: {e}")
                                pass

                        print("Stopping the server...")
                        try:
                            # First terminate the log process
                            current_server_process.terminate()
                            try:
                                # Wait for up to 5 seconds for the process to terminate
                                current_server_process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                print("Logs process did not terminate gracefully. Forcing shutdown...")
                                current_server_process.kill()
                                current_server_process.wait()

                            # Then shut down the Docker containers if we found the directory
                            if server_dir and os.path.exists(server_dir):
                                print(f"Stopping Docker containers in {server_dir}...")
                                try:
                                    stop_docker_compose(server_dir, None)
                                    # Remove from cleanup list
                                    if server_dir in docker_cleanup_dirs:
                                        docker_cleanup_dirs.remove(server_dir)
                                except Exception as e:
                                    print(f"Error stopping containers: {e}")

                            print("Server stopped successfully.")
                        except Exception as e:
                            print(f"Error stopping server: {e}")

                        current_server_process = None
                        continue
                    case None:
                        # For non-command input, use the entire text including multiple lines
                        content = ui
                    case _:
                        content = cmd

                # Send or continue conversation
                try:
                    print("\033[92mBot> \033[0m", end="", flush=True)
                    auth_token = os.environ.get("BUILDER_TOKEN")
                    if request is None:
                        logger.info("Sending new message") # This INFO log will be suppressed by module-level WARN
                        events, request = await client.send_message(
                            content,
                            settings=settings_dict,
                            auth_token=auth_token,
                            stream_cb=print_event
                        )
                    else:
                        logger.info("Sending continuation") # This INFO log will be suppressed by module-level WARN
                        events, request = await client.continue_conversation(
                            previous_events,
                            request,
                            content,
                            settings=settings_dict,
                            stream_cb=print_event
                        )
                    # Ensure newline after streaming events
                    print()

                    previous_messages.append(content)
                    previous_events.extend(events)
                    
                    # Save agent state to file if present
                    for event_item in reversed(events): # renamed 'event' to 'event_item' to avoid conflict
                        try:
                            if event_item.message and event_item.message.agent_state:
                                # Save state to a file in temp directory
                                state_file_path_temp = os.path.join(tempfile.gettempdir(), "agent_state.json") # Renamed to avoid conflict with outer state_file
                                with open(state_file_path_temp, "w") as f_state:
                                    json.dump(event_item.message.agent_state, f_state, indent=2)
                                print(f"\033[32mAgent state saved to: {os.path.abspath(state_file_path_temp)}\033[0m")
                                break  # Only save the most recent state
                        except AttributeError:
                            continue

                    if autosave:
                        with open(state_file, "w") as f_autosave: # Renamed to avoid conflict
                            json.dump({
                                "events": [e.model_dump() for e in previous_events],
                                "messages": previous_messages,
                                "agent_state": request.agent_state,
                                "timestamp": datetime.now().isoformat()
                            }, f_autosave, indent=2)
                except Exception as e:
                    print(f"Error: {e}")
                    traceback.print_exc()
                    
                    
@contextlib.contextmanager
def spawn_local_server(command: List[str] = ["uv", "run", "server"], host: str = "localhost", port: int = 8001):
    """
    Spawns a local server process and yields connection details.

    Args:
        command: Command to run the server as a list of strings
        host: Host to use for connection
        port: Port to use for connection

    Yields:
        Tuple of (host, port) for connecting to the server
    """
    proc = None
    std_err_file = None
    temp_dir = None

    try:
        temp_dir = tempfile.mkdtemp()
        std_err_file = open(os.path.join(temp_dir, "server_stderr.log"), "a+")
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=std_err_file,
            text=True
        )
        logger.info(f"Local server started, pid {proc.pid}, check `tail -f {std_err_file.name}` for logs")

        yield (host, port)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            logger.info("Terminated local server process")
        if std_err_file:
            std_err_file.close()
        if temp_dir:
            shutil.rmtree(temp_dir)
            logger.info(f"Removed temporary directory: {temp_dir}")


def cli(host: str = "",
        port: int = 8001,
        state_file: str = "/tmp/agent_chat_state.json",
        ):
    if not host:
        with spawn_local_server() as (local_host, local_port):
            anyio.run(run_chatbot_client, local_host, local_port, state_file, backend="asyncio")
    else:
        anyio.run(run_chatbot_client, host, port, state_file, backend="asyncio")


if __name__ == "__main__":
    try:
        import coloredlogs
        coloredlogs.install(level="WARN")
    except ImportError:
        pass

    from fire import Fire
    Fire(cli)
