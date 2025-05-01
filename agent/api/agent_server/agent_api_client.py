import json
import anyio
import os
import traceback
import tempfile
import shutil
import subprocess
import readline
import random
import string
import atexit
import time
import threading
from typing import List, Optional, Tuple
from log import get_logger
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.models import AgentSseEvent
from datetime import datetime
from patch_ng import PatchSet
import contextlib

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
                                        print(f"Warning: could not copy file {rel_file_path}: {cp_err}")

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


def apply_latest_diff(events: List[AgentSseEvent], custom_dir: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Apply the latest diff to a directory.
    
    Args:
        events: List of AgentSseEvent objects
        custom_dir: Optional custom base directory path
    
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
        # Create a timestamp-based project directory name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = f"project_{timestamp}"

        if custom_dir:
            base_dir = custom_dir
        else:
            base_dir = os.path.expanduser("~/projects")
            print(f"Using default project directory: {base_dir}")

        # Create the full project directory path
        target_dir = os.path.join(base_dir, project_name)

        # Apply the patch
        success, message = apply_patch(diff, target_dir)
        
        if success:
            return True, message, target_dir
        else:
            return False, message, target_dir
            
    except Exception as e:
        error_msg = f"Error applying diff: {e}"
        traceback.print_exc()
        return False, error_msg, None


docker_cleanup_dirs = []

def generate_random_name(prefix: str, length: int = 8) -> str:
    """Generate a random name with a prefix for Docker resources"""
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
    return f"{prefix}-{suffix}"

def cleanup_docker_projects():
    """Clean up any Docker projects that weren't properly shut down"""
    global docker_cleanup_dirs
    
    for project_dir in docker_cleanup_dirs:
        if os.path.exists(project_dir):
            print(f"Cleaning up Docker resources in {project_dir}")
            try:
                subprocess.run(
                    ["docker", "compose", "down", "-v"],
                    cwd=project_dir,
                    check=False,
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL
                )
            except Exception as e:
                print(f"Error during cleanup of {project_dir}: {e}")

atexit.register(cleanup_docker_projects)

# Global variable to store the currently running server logs
current_log_file = None

def save_log_line(log_file, line):
    """Append a log line to the log file with timestamp"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {line}\n")
    except Exception as e:
        logger.debug(f"Error saving log: {e}")

async def run_chatbot_client(host: str, port: int, state_file: str, settings: Optional[str] = None, autosave=False) -> None:
    """
    Async interactive Agent CLI chat.
    """
    # Make server process accessible globally
    global current_server_process, current_log_file

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
                            "/logs [n|head|tail] [count] View server logs with navigation (default: last 20 lines)"
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
                                base_dir = project_dir
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
                            
                        # Apply the diff to create a new project
                        custom_dir = rest[0] if rest else None
                        success, message, target_dir = apply_latest_diff(previous_events, custom_dir)
                        print(message)
                        
                        if success and target_dir:
                            print(f"\nSetting up project in {target_dir}...")
                            
                            # Generate random names for containers to avoid conflicts
                            db_container = generate_random_name("postgres")
                            app_container = generate_random_name("app")
                            frontend_container = generate_random_name("frontend")
                            network_name = generate_random_name("network")
                            db_push_container = generate_random_name("db-push")
                            
                            # Set environment variables instead of using .env file
                            # These will be picked up by docker-compose
                            os.environ["POSTGRES_CONTAINER_NAME"] = db_container
                            os.environ["BACKEND_CONTAINER_NAME"] = app_container 
                            os.environ["FRONTEND_CONTAINER_NAME"] = frontend_container
                            os.environ["DB_PUSH_CONTAINER_NAME"] = db_push_container
                            os.environ["NETWORK_NAME"] = network_name
                            
                            # Common database configuration
                            os.environ["POSTGRES_USER"] = "postgres"
                            os.environ["POSTGRES_PASSWORD"] = "postgres"
                            os.environ["POSTGRES_DB"] = "postgres"
                            
                            # Add to cleanup list
                            if target_dir not in docker_cleanup_dirs:
                                docker_cleanup_dirs.append(target_dir)
                            
                            print("Building services with Docker Compose...")
                            try:
                                # Build the services
                                subprocess.run(["docker", "compose", "build"], cwd=target_dir, check=True)
                                print("Dependencies installed successfully.")
                                
                                print("\nStarting development server with Docker Compose...")
                                # Ensure clean environment with down before starting
                                subprocess.run(
                                    ["docker", "compose", "down", "-v", "--remove-orphans"],
                                    cwd=target_dir,
                                    check=False
                                )
                                
                                # Start the services with the environment variables set
                                result = subprocess.run(
                                    ["docker", "compose", "up", "-d"],
                                    cwd=target_dir,
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                if result.returncode != 0:
                                    print(f"Warning: Docker Compose returned non-zero exit code: {result.returncode}")
                                    print(f"Error output: {result.stderr}")
                                else:
                                    print("All services started successfully.")
                                
                                # Create log file
                                logs_dir = os.path.join(target_dir, "logs")
                                os.makedirs(logs_dir, exist_ok=True)
                                log_file = os.path.join(logs_dir, f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                                current_log_file = log_file
                                
                                # Use Popen to follow the logs
                                current_server_process = subprocess.Popen(
                                    ["docker", "compose", "logs", "-f"],
                                    cwd=target_dir,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True
                                )
                                
                                # Start a background thread to read logs
                                def log_reader():
                                    while current_server_process and current_server_process.poll() is None:
                                        line = current_server_process.stdout.readline()
                                        if not line:
                                            time.sleep(0.1)
                                            continue
                                        
                                        line_str = line.rstrip()
                                        if current_log_file:
                                            save_log_line(current_log_file, line_str)
                                
                                # Start the log reader in a separate thread
                                log_thread = threading.Thread(target=log_reader, daemon=True)
                                log_thread.start()
                                
                                print("\nServer starting... Logs are being saved but not displayed.")
                                print(f"Full logs are saved to: {current_log_file}")
                                print(f"Use '/logs' command to view the logs.")
                                
                                print("\n🌐 Web UI is available at:")
                                print("   http://localhost:80 (for web servers, default HTTP port)")
                                
                                print(f"\nServer running in {target_dir}")
                                print("Use /stop command to stop the server when done.")
                                print("Use /logs to view server logs.")
                                
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
                                    subprocess.run(
                                        ["docker", "compose", "down", "-v"],
                                        cwd=server_dir,
                                        check=False
                                    )
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
                    case "/logs":
                        if not current_log_file or not os.path.exists(current_log_file):
                            print("No log file available. Start a server first with /run")
                            continue
                        
                        # Parse arguments
                        mode = "tail"  # Default mode shows the last lines
                        count = 20  # Default number of lines
                        
                        if rest:
                            args = rest[0].split()
                            if args:
                                if args[0] in ["head", "tail", "all"]:
                                    mode = args[0]
                                    if len(args) > 1 and args[1].isdigit():
                                        count = int(args[1])
                                elif args[0].isdigit():
                                    count = int(args[0])
                        
                        # Count total lines in the file
                        with open(current_log_file, "r", encoding="utf-8") as f:
                            total_lines = sum(1 for _ in f)
                        
                        print(f"\nLog file: {current_log_file}")
                        print(f"Total lines: {total_lines}")
                        
                        # Read the requested portion of the log
                        with open(current_log_file, "r", encoding="utf-8") as f:
                            if mode == "all":
                                lines = f.readlines()
                            elif mode == "head":
                                lines = [next(f) for _ in range(min(count, total_lines))]
                            else:  # tail mode
                                if count >= total_lines:
                                    f.seek(0)
                                    lines = f.readlines()
                                else:
                                    # Skip to the right position for tail
                                    for _ in range(total_lines - count):
                                        next(f)
                                    lines = f.readlines()
                        
                        # Display the logs with line numbers
                        start_line = 1 if mode == "head" else max(1, total_lines - count + 1) if mode == "tail" else 1
                        print(f"\nShowing {mode} {len(lines)} lines (of {total_lines}):")
                        print("=" * 80)
                        
                        for i, line in enumerate(lines):
                            line_num = start_line + i
                            print(f"{line_num:5d}: {line.rstrip()}")
                        
                        print("=" * 80)
                        print("Navigation commands:")
                        print("  /logs head [n]  - Show first n lines")
                        print("  /logs tail [n]  - Show last n lines")
                        print("  /logs all       - Show all lines (use with caution)")
                        print("  /logs [n]       - Show last n lines (shorthand for tail)")
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
