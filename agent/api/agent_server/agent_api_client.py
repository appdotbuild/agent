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

# ANSI escape codes for colors - Module Level
C_BLUE = '\033[94m'
C_GREEN = '\033[92m'
C_YELLOW = '\033[93m'
C_RED = '\033[91m'
C_MAGENTA = '\033[95m'
C_CYAN = '\033[96m'
C_GREY = '\033[90m' 
C_END = '\033[0m'
C_BOLD = '\033[1m'

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

# Helper function to copy template files, supporting overwrite
def _copy_template_files_recursive(base_dir, target_base, overwrite=False):
    """
    Copy all template files recursively, except those in excluded directories
    and hidden files (starting with a dot).
    If overwrite is True, existing files in target_base will be replaced.
    """
    excluded_dirs = ["node_modules", "dist"]
    for root, dirs, files_in_dir in os.walk(base_dir): # renamed files to files_in_dir
        dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith('.')]
        rel_path_from_template_root = os.path.relpath(root, base_dir)
        if rel_path_from_template_root == ".":
            rel_path_from_template_root = ""

        for file_item in files_in_dir:
            if file_item.startswith('.') or file_item.endswith('.md'):
                continue

            src_file = os.path.join(root, file_item)
            dest_file_rel_path = os.path.join(rel_path_from_template_root, file_item)
            dest_file_abs = os.path.join(target_base, dest_file_rel_path)
            dest_dir_abs = os.path.dirname(dest_file_abs)

            os.makedirs(dest_dir_abs, exist_ok=True)
            
            if os.path.lexists(dest_file_abs) and overwrite:
                try:
                    if os.path.isdir(dest_file_abs) and not os.path.islink(dest_file_abs):
                        shutil.rmtree(dest_file_abs) # Remove dir if overwriting
                    else:
                        os.remove(dest_file_abs) # Remove file/symlink
                except OSError as e_remove_overwrite:
                    print(f"{C_RED}  Warning: Could not remove for overwrite {dest_file_rel_path}: {e_remove_overwrite}{C_END}")
                    continue 
            
            if not os.path.lexists(dest_file_abs):
                try:
                    shutil.copy2(src_file, dest_file_abs)
                    # Minimal logging for this helper for now
                    # if overwrite: print(f"  Overwrote from template: {dest_file_rel_path}")
                    # else: print(f"  Copied from template: {dest_file_rel_path}")
                except Exception as cp_err:
                    print(f"{C_RED}  Warning: Could not copy file {dest_file_rel_path}: {cp_err}{C_END}")

def apply_patch(diff: str, target_dir: str, overwrite_project_from_template: bool = False) -> Tuple[bool, str]:
    try:
        print(f"Preparing to apply patch to directory: '{target_dir}'")
        target_dir = os.path.abspath(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile(suffix='.patch', delete=False) as tmp:
            tmp.write(diff.encode('utf-8'))
            tmp_path = tmp.name
            # Using C_YELLOW from module level as per diff.txt existing colors
            print(f"{C_YELLOW}Patch temp file: {os.path.abspath(tmp_path)}{C_END}")

        file_paths_in_diff = []
        with open(tmp_path, 'rb') as patch_file_for_paths:
            patch_set_for_paths = PatchSet(patch_file_for_paths)
            for item in patch_set_for_paths.items:
                if item.target:
                    target_path_str = item.target.decode('utf-8')
                    if target_path_str.startswith('b/'):
                        target_path_str = target_path_str[2:]
                    file_paths_in_diff.append(target_path_str)
        
        template_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../trpc_agent/template")
        )

        if os.path.isdir(template_root):
            if overwrite_project_from_template:
                print(f"{C_YELLOW}Resetting '{target_dir}' from template before patching...{C_END}")
                _copy_template_files_recursive(template_root, target_dir, overwrite=True)
            else:
                # For initial creation, ensure template files are present without full overwrite
                print(f"Copying template files to '{target_dir}' for initial setup...{C_END}")
                _copy_template_files_recursive(template_root, target_dir, overwrite=False)
        else:
            print(f"{C_RED}Warning: Template directory not found at {template_root}. Cannot prepare template files.{C_END}")

        # The original complex symlink logic from 6ba8c4f7... is now replaced by the above.

        original_dir = os.getcwd()
        try:
            os.chdir(target_dir)
            print(f"Changed to directory: {target_dir}")

            # Pre-create directories for files mentioned in the patch if they don't exist
            for path_in_diff in file_paths_in_diff:
                if '/' in path_in_diff:
                    dir_of_file_in_diff = os.path.dirname(path_in_diff)
                    if dir_of_file_in_diff:
                        os.makedirs(dir_of_file_in_diff, exist_ok=True)
            
            print(f"{C_CYAN}Applying patch using python-patch-ng...{C_END}")
            with open(tmp_path, 'rb') as patch_file_to_apply:
                patch_set = PatchSet(patch_file_to_apply)
                success = patch_set.apply(strip=0)

            # Move misplaced files (same as current-base)
            for path_in_diff in file_paths_in_diff:
                if '/' in path_in_diff:
                    basename = os.path.basename(path_in_diff)
                    dirname = os.path.dirname(path_in_diff)
                    if os.path.exists(basename) and not os.path.exists(path_in_diff) and dirname:
                        print(f"{C_YELLOW}Moving {basename} to {path_in_diff}{C_END}")
                        os.makedirs(dirname, exist_ok=True)
                        os.rename(basename, path_in_diff)

            if success:
                return True, f"Successfully applied patch to '{target_dir}'"
            else:
                return False, f"{C_RED}Failed to apply patch to '{target_dir}' (hunks rejected/mismatched).{C_END}"
        finally:
            os.chdir(original_dir)
            os.unlink(tmp_path)
    except Exception as e:
        traceback.print_exc()
        return False, f"{C_RED}Error in apply_patch: {e}{C_END}"


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


def apply_latest_diff(events: List[AgentSseEvent], output_dir: str) -> Tuple[bool, str, Optional[str]]:
    """
    Apply the latest diff to the specified output directory.
    If output_dir exists, files will be reset from template before patching.
    """
    diff = latest_unified_diff(events)
    if not diff:
        return False, "No diff available to apply", None
    try:
        # output_dir is already resolved by the caller (e.g. /run command)
        print(f"Applying diff to target directory: {output_dir}")
        should_overwrite = os.path.isdir(output_dir) # If dir exists, it implies re-apply or update
        if should_overwrite:
            print(f"{C_YELLOW}Target '{output_dir}' exists. Will reset from template before patching.{C_END}")

        # Call our refactored apply_patch
        success, message = apply_patch(diff, output_dir, overwrite_project_from_template=should_overwrite)

        if success:
            return True, message, output_dir
        else:
            return False, message, output_dir
    except Exception as e:
        error_msg = f"Error in apply_latest_diff: {e}"
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

async def run_chatbot_client(host: str, port: int, state_file_path_arg: str, settings: Optional[str] = None, autosave=False) -> None:
    """
    Async interactive Agent CLI chat.
    """
    # Make server process accessible globally
    global current_server_process

    # Prepare state and settings
    state_file_path_arg = os.path.expanduser(state_file_path_arg)
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
    if os.path.exists(state_file_path_arg):
        try:
            with open(state_file_path_arg, "r") as f_state_load:
                saved = json.load(f_state_load)
                previous_events = [AgentSseEvent.model_validate(e) for e in saved.get("events", []) if isinstance(e, dict)]
                previous_messages = saved.get("messages", [])
                print(f"Loaded conversation with {len(previous_messages)} messages from {state_file_path_arg}")
        except Exception as e_load:
            print(f"Warning: could not load state from {state_file_path_arg}: {e_load}")

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
    last_event_time = None

    def print_event(event: AgentSseEvent) -> None:
        """Pretty-print incoming SSE events.

        - Handles chat history, displaying only new messages.
        - Saves large content/diffs/agent_states to temp files and prints paths.
        - Provides a summary of key fields if agent_state is present in an event.
        - Displays timing between event processing.
        """
        nonlocal displayed_message_count, last_event_time
        current_time = datetime.now()

        # ANSI escape codes for colors - MOVED TO THE TOP (now referencing module level)
        # Definitions removed from here

        # Add a newline before each event's output for separation
        print() 

        if last_event_time:
            duration = current_time - last_event_time
            duration_seconds = duration.total_seconds()
            print(f"{C_GREY}(... processed in {duration_seconds:.2f} seconds ...){C_END}")
            print() 
        
        last_event_time = current_time

        msg = event.message
        if not msg:
            return

        # 0. Report Agent State from this specific event (summary, not diff)
        if msg.agent_state:
            try:
                state_timestamp = datetime.now().strftime("%H%M%S_%f")
                state_event_filename = f"agent_state_event_{state_timestamp}.json"
                state_event_filepath = os.path.join(tempfile.gettempdir(), state_event_filename)
                with open(state_event_filepath, "w") as f_event_state:
                    json.dump(msg.agent_state, f_event_state, indent=2)
                print(f"{C_GREEN}[state] update in event, full state saved to: {os.path.abspath(state_event_filepath)}{C_END}")
                
                # Print a summary of the current agent_state
                if isinstance(msg.agent_state, dict):
                    print(f"{C_GREEN}  Current Agent State Summary:{C_END}")
                    fsm_state = msg.agent_state.get("fsm_state")
                    if isinstance(fsm_state, dict):
                        current_fsm_val = fsm_state.get("current_state")
                        if current_fsm_val is not None: print(f"{C_GREEN}  ├─ FSM State: {current_fsm_val}{C_END}")
                        stack_p = fsm_state.get("stack_path")
                        if stack_p: print(f"{C_GREEN}  │  └─ Stack: {stack_p}{C_END}")
                        
                        context = fsm_state.get("context")
                        if isinstance(context, dict):
                            print(f"{C_GREEN}  ├─ Context Summary:{C_END}")
                            user_p = context.get("user_prompt", "")
                            if user_p: print(f"{C_GREEN}  │  ├─ User Prompt: {(user_p[:70] + '...') if len(user_p) > 70 else user_p}{C_END}")
                            files_ctx = context.get("files", {})
                            if files_ctx : print(f"{C_GREEN}  │  ├─ Files in Context: {len(files_ctx)} ({list(files_ctx.keys())[:3]}...){C_END}")
                            else: print(f"{C_GREEN}  │  ├─ Files in Context: 0{C_END}")
                            err_ctx = context.get("error")
                            if err_ctx is not None: print(f"{C_GREEN}  │  └─ Error: {err_ctx}{C_END}")

                    actors = msg.agent_state.get("actors")
                    if isinstance(actors, list):
                        actor_paths = [str(actor.get("path", "N/A")) for actor in actors]
                        if actor_paths: print(f"{C_GREEN}  ├─ Actors: {", ".join(actor_paths)[:100]}...{C_END}")
                        # Further actor details (like draft summary) can be added here if concise
                elif isinstance(msg.agent_state, (str, int, float, bool)):
                     print(f"{C_GREEN}  └─ State Value: {msg.agent_state}{C_END}")

            except Exception as e_state_process: # Renamed variable
                print(f"{C_RED}[state] error processing/saving event-specific state: {e_state_process}{C_END}")

        # 1. Handle diff payloads --------------------------------------------------
        if msg.unified_diff:
            try:
                with tempfile.NamedTemporaryFile(suffix="_received.patch", delete=False, mode="w", encoding="utf-8") as tmp_diff:
                    tmp_diff.write(msg.unified_diff)
                    print(f"{C_CYAN}[diff] saved: {os.path.abspath(tmp_diff.name)}{C_END}")
            except Exception as e_diff:
                print(f"{C_RED}[diff] error saving: {e_diff}{C_END}")

        # 2. Handle content ---------------------------------------------------------
        if msg.content:
            content_raw = msg.content  # May be str or other type
            # a) Chat-history JSON array (string) -----------------------------------
            if isinstance(content_raw, str) and content_raw.lstrip().startswith('['):
                try:
                    history = json.loads(content_raw)
                except json.JSONDecodeError:
                    history = None

                if isinstance(history, list) and all(isinstance(m_dict, dict) for m_dict in history):
                    new_messages = history[displayed_message_count:]
                    if new_messages:
                        for m_item in new_messages:
                            role = m_item.get("role", "unknown")
                            role_color = C_BLUE if role == "assistant" else C_YELLOW
                            prefix = f"{role_color}[{role}]{C_END}"
                            print(prefix, end=" ")
                            for item in m_item.get("content", []):
                                if isinstance(item, dict):
                                    t = item.get("type")
                                    if t == "text":
                                        print(item.get('text', '').strip(), end=" ")
                                    elif t == "tool_use":
                                        tool_name = item.get('name', 'unknown_tool')
                                        tool_id = item.get('id', 'N/A')
                                        print(f"{C_MAGENTA}[{t}:{tool_name} (id:{tool_id})] {C_END}", end=" ")
                                    elif t == "tool_use_result":
                                        tool_name = item.get('name', 'unknown_tool')
                                        print(f"{C_MAGENTA}[{t}:{tool_name}] {C_END}", end=" ")
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
                    ui = get_multiline_input(f"{C_YELLOW}You> {C_END}")
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
                        with open(state_file_path_arg, "w") as f_save:
                            json.dump({
                                "events": [e.model_dump() for e in previous_events],
                                "messages": previous_messages,
                                "agent_state": request.agent_state if request else None,
                                "timestamp": datetime.now().isoformat()
                            }, f_save, indent=2)
                        print(f"State saved to {state_file_path_arg}")
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
                        diff_to_apply = latest_unified_diff(previous_events)
                        if not diff_to_apply:
                            print("No diff to apply.")
                            continue
                        
                        apply_target_dir = ""
                        should_overwrite_apply = False
                        if rest and rest[0]:
                            apply_target_dir = os.path.abspath(rest[0])
                            print(f"Applying to specified directory: {apply_target_dir}")
                            if os.path.isdir(apply_target_dir): # Specified dir exists
                                should_overwrite_apply = True 
                        else:
                            # Default: create new timestamped subdir in session's project_dir
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            project_name_ts = f"project_{timestamp}"
                            apply_target_dir = os.path.join(project_dir, project_name_ts)
                            print(f"Applying to new directory: {apply_target_dir}")
                            # should_overwrite_apply remains False for new dirs
                        
                        os.makedirs(apply_target_dir, exist_ok=True)
                        s_apply, m_apply = apply_patch(diff_to_apply, apply_target_dir, overwrite_project_from_template=should_overwrite_apply)
                        print(m_apply)
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
                        run_custom_dir_arg = rest[0] if rest else None
                        run_target_dir = ""
                        if run_custom_dir_arg:
                            run_target_dir = os.path.abspath(run_custom_dir_arg)
                            print(f"Run: Using specified directory: {run_target_dir}")
                        else:
                            # Default for /run: create new timestamped project in session AGENT_PROJECT_DIR (or temp)
                            # This aligns with apply_latest_diff creating a new dir if no custom_dir is passed to it in base
                            timestamp_run = datetime.now().strftime("%Y%m%d_%H%M%S")
                            project_name_run = f"project_{timestamp_run}"
                            run_target_dir = os.path.join(project_dir, project_name_run) # project_dir is from context
                            print(f"Run: Creating new project in: {run_target_dir}")
                        
                        os.makedirs(run_target_dir, exist_ok=True) # Ensure it exists before passing to apply_latest_diff
                        
                        s_run, m_run, final_run_dir = apply_latest_diff(previous_events, run_target_dir)
                        print(m_run)
                        
                        if s_run and final_run_dir:
                            # Docker logic from diff.txt (current-base)
                            print(f"\nSetting up project in {final_run_dir}...")
                            # ... (rest of docker setup, start_docker_compose, Popen for logs) ...
                            # This section is complex and taken as-is from diff.txt
                            container_names = setup_docker_env()
                            if final_run_dir not in docker_cleanup_dirs: docker_cleanup_dirs.append(final_run_dir)
                            print("Building services with Docker Compose...")
                            try:
                                s_compose, err_compose = start_docker_compose(final_run_dir, container_names["project_name"], build=True)
                                if not s_compose: print(f"Warning: Docker Compose error: {err_compose}")
                                else: 
                                    print("All services started.")
                                    print("\n🌐 Web UI: http://localhost:80 (default)") # Port assumed
                                    current_server_process = subprocess.Popen(["docker", "compose", "logs", "-f"], cwd=final_run_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                                    # ... (print initial server output) ...
                                    print(f"\nServer running in {final_run_dir}. Use /stop.")
                            except Exception as e_docker: print(f"Error during project setup: {e_docker}")
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
                    print(f"{C_BLUE}Bot> {C_END}", end="", flush=True)
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
                        with open(state_file_path_arg, "w") as f_autosave: # Renamed to avoid conflict
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
