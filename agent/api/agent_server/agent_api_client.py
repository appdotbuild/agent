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
import shlex
import argparse
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

# Class to capture command output for piping
class CommandOutput:
    def __init__(self, text=None, lines=None):
        if lines is not None:
            self.lines = lines
        elif text is not None:
            self.lines = text.splitlines()
        else:
            self.lines = []
            
    def __str__(self):
        return "\n".join(self.lines)
    
    def __bool__(self):
        return bool(self.lines)
        
    def append(self, line):
        self.lines.append(line)
    
    def extend(self, lines):
        self.lines.extend(lines)
    
    def grep(self, pattern):
        """Filter lines by pattern"""
        return CommandOutput(lines=[line for line in self.lines if pattern.lower() in line.lower()])
    
    def head(self, n):
        """Get first n lines"""
        return CommandOutput(lines=self.lines[:n])
    
    def tail(self, n):
        """Get last n lines"""
        return CommandOutput(lines=self.lines[-n:])
    
    def count(self):
        return len(self.lines)

# Custom ArgumentParser that doesn't exit on error
class CommandArgumentParser(argparse.ArgumentParser):
    def exit(self, status=0, message=None):
        if message:
            self._print_message(message)
    
    def error(self, message):
        self.print_usage()
        self.print_help()
        raise ValueError(f"Error: {message}")

    def parse_args_safe(self, args=None, namespace=None):
        try:
            return self.parse_args(args, namespace)
        except Exception as e:
            print(f"Error parsing arguments: {e}")
            print(self.format_help())
            return None

# Create command parsers
def create_logs_parser():
    parser = CommandArgumentParser(prog="/logs", description="View server logs with filtering options")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--head", type=int, metavar="N", help="Show first N lines")
    mode_group.add_argument("--tail", type=int, metavar="N", help="Show last N lines")
    mode_group.add_argument("--all", action="store_true", help="Show all lines (use with caution)")
    mode_group.add_argument("-n", "--lines", type=int, default=20, help="Number of lines to show (default: 20)")
    parser.add_argument("-g", "--grep", metavar="PATTERN", help="Filter lines containing pattern")
    parser.add_argument("pattern", nargs="*", help="Additional pattern words (combined with --grep)")
    return parser

def create_feedback_parser():
    parser = CommandArgumentParser(prog="/feedback", description="Send feedback to the agent with optional logs")
    parser.add_argument("-n", "--lines", type=int, default=0, metavar="N", 
                        help="Include last N lines of logs (default: 0, no logs)")
    parser.add_argument("message", nargs="*", help="Feedback message (optional, will prompt if not provided)")
    return parser

def create_help_parser():
    parser = CommandArgumentParser(prog="/help", description="Show help for available commands")
    parser.add_argument("command", nargs="?", help="Show help for specific command")
    return parser

# Command handler functions
async def handle_logs(args, previous_output=None, client=None, **kwargs):
    """Handle the /logs command, optionally with piped input"""
    if not current_log_file or not os.path.exists(current_log_file):
        print("No log file available. Start a server first with /run")
        return CommandOutput()
    
    # Parse arguments with argparse
    parser = create_logs_parser()
    parsed_args = parser.parse_args_safe(args)
    if not parsed_args:
        return CommandOutput()
    
    # Determine mode and count from arguments
    mode = "tail"  # Default
    count = parsed_args.lines
    
    if parsed_args.head is not None:
        mode = "head"
        count = parsed_args.head
    elif parsed_args.tail is not None:
        mode = "tail"
        count = parsed_args.tail
    elif parsed_args.all:
        mode = "all"
        count = 0  # Not used for "all" mode
    
    # Combine grep and pattern
    pattern = None
    if parsed_args.grep or parsed_args.pattern:
        pattern_parts = []
        if parsed_args.grep:
            pattern_parts.append(parsed_args.grep)
        if parsed_args.pattern:
            pattern_parts.extend(parsed_args.pattern)
        pattern = " ".join(pattern_parts)
    
    # If this is a piped command and we have input, use that instead of reading the file
    if previous_output:
        all_lines = previous_output.lines
        total_lines = len(all_lines)
        print(f"Using {total_lines} lines from previous command")
        
        # Apply grep pattern first to all lines
        if pattern:
            print(f"\nGrepping for: '{pattern}'")
            filtered_lines = [line for line in all_lines if pattern.lower() in line.lower()]
            print(f"Found {len(filtered_lines)} matching lines out of {len(all_lines)}")
            all_lines = filtered_lines
            
        # Then apply mode filtering (head/tail)
        if mode == "head" and not parsed_args.all:
            display_lines = all_lines[:count]
        elif mode == "tail" and not parsed_args.all:
            display_lines = all_lines[-count:]
        else:
            display_lines = all_lines
            
    else:
        # Count total lines in the file
        with open(current_log_file, "r", encoding="utf-8") as f:
            total_lines = sum(1 for _ in f)
        
        print(f"\nLog file: {current_log_file}")
        print(f"Total lines: {total_lines}")
        
        # If pattern is specified, we need to grep the entire file first
        if pattern:
            # Read all lines from the file
            with open(current_log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            
            print(f"\nGrepping for: '{pattern}'")
            filtered_lines = [line for line in all_lines if pattern.lower() in line.lower()]
            print(f"Found {len(filtered_lines)} matching lines out of {total_lines}")
            
            # Store original line numbers for accurate display
            line_nums = []
            for i, line in enumerate(all_lines):
                if pattern.lower() in line.lower():
                    line_nums.append(i + 1)  # 1-indexed line numbers
            
            # Then apply mode filtering (head/tail)
            if mode == "head" and not parsed_args.all:
                display_lines = filtered_lines[:count]
                display_line_nums = line_nums[:count]
            elif mode == "tail" and not parsed_args.all:
                display_lines = filtered_lines[-count:]
                display_line_nums = line_nums[-count:]
            else:
                display_lines = filtered_lines
                display_line_nums = line_nums
        
        else:
            # No pattern, just apply mode filtering directly
            with open(current_log_file, "r", encoding="utf-8") as f:
                if mode == "all":
                    display_lines = f.readlines()
                elif mode == "head":
                    display_lines = [next(f) for _ in range(min(count, total_lines))]
                else:  # tail mode
                    if count >= total_lines:
                        f.seek(0)
                        display_lines = f.readlines()
                    else:
                        # Skip to the right position for tail
                        for _ in range(total_lines - count):
                            next(f)
                        display_lines = f.readlines()
                
            # Generate line numbers for display
            if mode == "tail" and count < total_lines:
                start_line = max(1, total_lines - len(display_lines) + 1)
            else:
                start_line = 1
            display_line_nums = list(range(start_line, start_line + len(display_lines)))
    
    # Display the logs with line numbers
    display_mode = "grep" if pattern else mode
    display_count = len(display_lines)
    print(f"\nShowing {display_count} lines ({display_mode}{' ' + str(count) if count and mode != 'all' else ''}):")
    print("=" * 80)
    
    if previous_output and pattern:
        # For piped output with grep, we don't have original line numbers
        for i, line in enumerate(display_lines):
            print(f"{i+1:5d}: {line.rstrip()}")
    else:
        # Use stored line numbers or calculated line numbers
        for i, line in enumerate(display_lines):
            if pattern and not previous_output:
                line_num = display_line_nums[i]
            else:
                line_num = display_line_nums[i]
            print(f"{line_num:5d}: {line.rstrip()}")
    
    print("=" * 80)
    if not previous_output:
        print("Examples:")
        print("  /logs --tail 20        - Show last 20 lines")
        print("  /logs --head 30        - Show first 30 lines")
        print("  /logs --all            - Show all lines (use with caution)")
        print("  /logs -n 50            - Show last 50 lines")
        print("  /logs --grep error     - Filter lines containing 'error'")
        print("  /logs error            - Same as above")
        print("  /logs | feedback       - Pipe filtered logs to feedback")
    
    # Return output for piping
    return CommandOutput(lines=[line.rstrip() for line in display_lines])


async def handle_feedback(args, previous_output=None, client=None, **kwargs):
    """Handle the /feedback command with optional piped input"""
    if not client:
        print("Error: Client not available")
        return CommandOutput()
        
    # Extract necessary parameters from kwargs
    request = kwargs.get("request")
    previous_events = kwargs.get("previous_events", [])
    previous_messages = kwargs.get("previous_messages", [])
    settings_dict = kwargs.get("settings_dict", {})
    state_file = kwargs.get("state_file", "")
    autosave = kwargs.get("autosave", False)
    
    # Parse arguments with argparse
    parser = create_feedback_parser()
    parsed_args = parser.parse_args_safe(args)
    if not parsed_args:
        return CommandOutput()
    
    # Get line count and message from arguments
    log_lines_count = parsed_args.lines
    feedback_text = " ".join(parsed_args.message) if parsed_args.message else None
    
    # If we have piped input, use that instead of reading from file
    log_section = ""
    
    # If we don't have feedback text yet, prompt for it
    if feedback_text is None:
        print("\nEnter your feedback (finish with an empty line):")
        feedback_lines = []
        while True:
            line = input()
            if not line.strip():
                break
            feedback_lines.append(line)
        
        feedback_text = "\n".join(feedback_lines)
    
    if not feedback_text.strip() and not previous_output:
        print("Feedback message cannot be empty without piped content. Aborting.")
        return CommandOutput()
    
    # Add log section
    if previous_output:
        # Use the piped input as our log content
        log_section = "\n\n## Logs\n```\n{}```".format("\n".join(previous_output.lines))
    elif log_lines_count > 0 and current_log_file and os.path.exists(current_log_file):
        # Get logs from file if requested
        with open(current_log_file, "r", encoding="utf-8") as f:
            total_lines = sum(1 for _ in f)
        
        with open(current_log_file, "r", encoding="utf-8") as f:
            if log_lines_count >= total_lines:
                log_lines = f.readlines()
            else:
                for _ in range(total_lines - log_lines_count):
                    next(f)
                log_lines = f.readlines()
        
        log_section = "\n\n## Server Logs (last {} lines)\n```\n{}```".format(
            len(log_lines), "".join(log_lines)
        )
    
    # Combine feedback with logs
    if feedback_text.strip():
        content = f"## Feedback\n{feedback_text}{log_section}"
    else:
        content = f"# Log Output{log_section}"
    
    # Preview the message
    print("\nYour message will look like this:")
    print("-" * 40)
    
    # Show a preview (truncated if too long)
    preview = content
    if len(preview) > 500:
        preview = preview[:497] + "..."
    print(preview)
    
    print("-" * 40)
    confirm = input("Send this to the agent? (Y/n): ")
    if confirm.lower() in ('n', 'no'):
        print("Message not sent")
        return CommandOutput()
    
    print("\nSending to agent...\n")
    
    try:
        print("\033[92mBot> \033[0m", end="", flush=True)
        auth_token = os.environ.get("BUILDER_TOKEN")
        if request is None:
            logger.warning("Sending new message")
            events, new_request = await client.send_message(content, settings=settings_dict, auth_token=auth_token)
        else:
            logger.warning("Sending continuation")
            events, new_request = await client.continue_conversation(previous_events, request, content)

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
                    "agent_state": new_request.agent_state,
                    "timestamp": datetime.now().isoformat()
                }, f, indent=2)
                
        # Update the request in kwargs for the calling function
        kwargs["request"] = new_request
    except Exception as e:
        print(f"Error sending message: {e}")
        traceback.print_exc()
    
    return CommandOutput()

async def handle_help(args, previous_output=None, **kwargs):
    """Display help information"""
    project_dir = kwargs.get("project_dir", "~/projects")
    
    # Parse arguments with argparse
    parser = create_help_parser()
    parsed_args = parser.parse_args_safe(args)
    if not parsed_args:
        return CommandOutput()
    
    # If a specific command was requested, show help for just that command
    if parsed_args.command and parsed_args.command.startswith('/'):
        cmd = parsed_args.command
        if cmd == "/logs":
            create_logs_parser().print_help()
        elif cmd == "/feedback":
            create_feedback_parser().print_help()
        elif cmd == "/help":
            create_help_parser().print_help()
        else:
            print(f"No detailed help available for {cmd}")
        return CommandOutput()
    
    # Otherwise show general help
    print(
        "Commands:\n"
        "/help [command]  Show help for all commands or specific command\n"
        "/exit, /quit     Exit chat\n"
        "/clear           Clear conversation\n"
        "/save            Save state to file"
        "\n"
        "/diff            Show the latest unified diff\n"
        f"/apply [dir]    Apply the latest diff to directory (default: {project_dir})\n"
        "/export          Export the latest diff to a patchfile\n"
        "/run [dir]       Apply diff, install deps, and start dev server\n"
        "/stop            Stop the currently running server\n"
        "/logs            View server logs with filter (use /help /logs for details)\n"
        "/feedback        Send feedback to the agent (use /help /feedback for details)\n"
        "\nPipe Support:\n"
        "  command1 | command2     Pass output from command1 to command2\n"
        "  /logs --grep error | feedback  Filter logs and send in feedback\n"
        "  /logs -n 50 | feedback         Get 50 lines and send in feedback\n"
    )
    return CommandOutput()

# Command registry
commands = {
    "/help": handle_help,
    "/logs": handle_logs,
    "/feedback": handle_feedback,
}

def extract_latest_diff(events: List[AgentSseEvent]) -> Optional[str]:
    """Extract the latest diff from a list of events"""
    return latest_unified_diff(events)

async def start_server_in_directory(target_dir: str) -> Tuple[bool, str]:
    """Start server in the specified directory using Docker Compose"""
    global current_server_process, current_log_file
    
    if not os.path.exists(target_dir):
        return False, f"Directory does not exist: {target_dir}"
    
    # Stop any currently running server
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
    
    print(f"Starting server in {target_dir}...")
    
    db_container = generate_random_name("postgres")
    app_container = generate_random_name("app")
    frontend_container = generate_random_name("frontend")
    network_name = generate_random_name("network")
    db_push_container = generate_random_name("db-push")
    
    os.environ["POSTGRES_CONTAINER_NAME"] = db_container
    os.environ["BACKEND_CONTAINER_NAME"] = app_container 
    os.environ["FRONTEND_CONTAINER_NAME"] = frontend_container
    os.environ["DB_PUSH_CONTAINER_NAME"] = db_push_container
    os.environ["NETWORK_NAME"] = network_name
    
    os.environ["POSTGRES_USER"] = "postgres"
    os.environ["POSTGRES_PASSWORD"] = "postgres"
    os.environ["POSTGRES_DB"] = "postgres"
    
    if target_dir not in docker_cleanup_dirs:
        docker_cleanup_dirs.append(target_dir)
    
    # Create log file BEFORE starting Docker
    logs_dir = os.path.join(target_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    current_log_file = log_file
    
    save_log_line(current_log_file, "Starting server setup...")
    
    try:
        print("Building services with Docker Compose...")
        build_result = subprocess.run(
            ["docker", "compose", "build"], 
            cwd=target_dir, 
            capture_output=True,
            text=True,
            check=False
        )
        
        if build_result.returncode != 0:
            error_msg = f"Docker Compose build failed with code {build_result.returncode}"
            print(f"Error: {error_msg}")
            save_log_line(current_log_file, error_msg)
            save_log_line(current_log_file, build_result.stdout)
            save_log_line(current_log_file, build_result.stderr)
            return False, error_msg
        
        print("Dependencies installed successfully.")
        save_log_line(current_log_file, "Build completed successfully")
        
        print("\nStarting development server with Docker Compose...")
        save_log_line(current_log_file, "Starting Docker services...")
        
        # Ensure clean environment with down before starting
        down_result = subprocess.run(
            ["docker", "compose", "down", "-v", "--remove-orphans"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        if down_result.stdout:
            save_log_line(current_log_file, down_result.stdout)
        if down_result.stderr:
            save_log_line(current_log_file, down_result.stderr)
        
        # Start the services with the environment variables set
        result = subprocess.run(
            ["docker", "compose", "up", "-d"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=False
        )
        
        # Log the output regardless of success or failure
        if result.stdout:
            save_log_line(current_log_file, result.stdout)
        if result.stderr:
            save_log_line(current_log_file, result.stderr)
        
        if result.returncode != 0:
            error_msg = f"Docker Compose returned non-zero exit code: {result.returncode}"
            print(f"Warning: {error_msg}")
            save_log_line(current_log_file, f"Docker Compose error (code {result.returncode})")
            save_log_line(current_log_file, result.stderr)
            return False, error_msg
        
        print("All services started successfully.")
        save_log_line(current_log_file, "All services started successfully")
        
        # Ensure we capture ALL logs - both historical and new
        def collect_historical_logs():
            """Collect all historical logs at startup to ensure nothing is missed"""
            try:
                save_log_line(current_log_file, "Collecting historical Docker logs...")
                # Get all logs without follow flag to capture history
                result = subprocess.run(
                    ["docker", "compose", "logs", "--no-color"],
                    cwd=target_dir,
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.stdout:
                    # Process and save all historical log lines
                    for line in result.stdout.splitlines():
                        save_log_line(current_log_file, line)
                    
                save_log_line(current_log_file, "Historical logs collection completed")
            except Exception as e:
                save_log_line(current_log_file, f"Error collecting historical logs: {e}")
        
        # Start historical log collection in a separate thread
        hist_thread = threading.Thread(target=collect_historical_logs, daemon=True)
        hist_thread.start()
        
        # Use Popen to follow the logs (for new logs)
        current_server_process = subprocess.Popen(
            ["docker", "compose", "logs", "--follow", "--no-color", "--timestamps"],
            cwd=target_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Start a background thread to read logs
        def log_reader():
            error_patterns = [
                "Error:", "ERROR:", "Exception:", "EXCEPTION:",
                "Failed to", "failed to",
                "Bind for", "port is already allocated",
                "Connection refused",
                "exited with code",
                "Exited with code",
                "OCI runtime",
                "npm ERR!",
                "error Command failed",
                "syntax error",
                "Cannot start service",
                "denied: requested access to the resource is denied",
                "Permission denied"
            ]
            
            critical_errors_shown = set()  # Track errors we've already shown
            last_alert_time = time.time()  # Rate limit error alerts
            last_sync_time = time.time()   # Track last resync time
            
            # Periodically sync logs to catch any logs from restarted containers
            def resync_logs():
                nonlocal last_sync_time
                # Only resync every 30 seconds to avoid performance issues
                current_time = time.time()
                if current_time - last_sync_time < 30:
                    return
                    
                # Check if we have active containers that might have restarted
                try:
                    ps_result = subprocess.run(
                        ["docker", "compose", "ps", "--format", "json"],
                        cwd=target_dir,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    # If we got container list, check if any have restarted recently
                    if ps_result.returncode == 0 and ps_result.stdout.strip():
                        save_log_line(current_log_file, "Resyncing logs to catch any missed entries...")
                        # Get latest logs in a single batch (last 100 lines from each container)
                        resync_result = subprocess.run(
                            ["docker", "compose", "logs", "--no-color", "--tail=100"],
                            cwd=target_dir,
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        # Only log info about the resync, not the actual logs
                        # as they'll appear in the continuous follow
                        if resync_result.returncode == 0:
                            save_log_line(current_log_file, "Log resync completed")
                        
                    last_sync_time = current_time
                except Exception as e:
                    save_log_line(current_log_file, f"Error during log resync: {e}")
            
            while current_server_process and current_server_process.poll() is None:
                line = current_server_process.stdout.readline()
                if not line:
                    # When there's no output, check if we need to resync
                    # This helps catch logs after container restarts
                    resync_logs()
                    time.sleep(0.1)
                    continue
                
                line_str = line.rstrip()
                if current_log_file:
                    save_log_line(current_log_file, line_str)
                
                # Check for error patterns in the log line
                for pattern in error_patterns:
                    if pattern in line_str:
                        # Create a hash of the error to avoid duplicates
                        error_hash = hash(line_str[:100])
                        
                        # Only show each unique error once and rate limit
                        current_time = time.time()
                        if (error_hash not in critical_errors_shown and 
                                current_time - last_alert_time > 2.0):
                            critical_errors_shown.add(error_hash)
                            last_alert_time = current_time
                            
                            # Display the error in the console
                            print(f"\n\033[91m🚨 SERVER ERROR DETECTED: \033[0m")
                            print(f"\033[91m{line_str}\033[0m")
                            print(f"Use '/logs' command to view full logs.")
                            
                        break  # Stop checking other patterns for this line
        
        # Start the log reader in a separate thread
        log_thread = threading.Thread(target=log_reader, daemon=True)
        log_thread.start()
        
        print("\nServer starting... Logs are being saved but not displayed.")
        print(f"Full logs are saved to: {current_log_file}")
        print("Use '/logs' command to view the logs.")
        print("Error detection is active - critical errors will be shown automatically.")
        
        print("\n🌐 Web UI is available at:")
        print("   http://localhost:80 (for web servers, default HTTP port)")
        
        print(f"\nServer running in {target_dir}")
        
        return True, f"Server started successfully in {target_dir}"
        
    except Exception as e:
        error_msg = f"Error starting server: {e}"
        print(error_msg)
        save_log_line(current_log_file, error_msg)
        return False, error_msg

async def run_chatbot_client(
    host: str, 
    port: int, 
    state_file: str, 
    settings: Optional[str] = None,
    autosave=False,
    # Non-interactive mode parameters
    message: Optional[str] = None,
    apply_to: Optional[str] = None,
    run: bool = False,
    output_file: Optional[str] = None
) -> None:
    """
    Async interactive Agent CLI chat.
    
    If message is provided, runs in non-interactive mode:
    - Sends the specified message to the agent
    - Optionally applies any diff to apply_to directory
    - Optionally runs the server if run=True
    - Optionally saves output to output_file
    - Exits after completion
    """
    # Make server process accessible globally
    global current_server_process

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

    # Check for non-interactive mode
    if message is not None:
        print("Running in non-interactive mode")
        if host:
            base_url = f"http://{host}:{port}"
            print(f"Connected to {base_url}")
        else:
            base_url = None # Use ASGI transport for local testing
            
        async with AgentApiClient(base_url=base_url) as client:
            with project_dir_context() as project_dir:
                try:
                    print(f"Sending message: {message}")
                    print("\033[92mBot> \033[0m", end="", flush=True)
                    
                    auth_token = os.environ.get("BUILDER_TOKEN")
                    if request is None:
                        logger.warning("Sending new message")
                        events, request = await client.send_message(message, settings=settings_dict, auth_token=auth_token)
                    else:
                        logger.warning("Sending continuation")
                        events, request = await client.continue_conversation(previous_events, request, message)
                    
                    response_text = ""
                    
                    for evt in events:
                        if evt.message and evt.message.content:
                            content = evt.message.content
                            response_text += content
                            print(content, end="", flush=True)
                            
                        # Automatically print diffs when they're provided
                        if evt.message and evt.message.unified_diff:
                            print("\n\n\033[36m--- Auto-Detected Diff ---\033[0m")
                            print(f"\033[36m{evt.message.unified_diff}\033[0m")
                            print("\033[36m--- End of Diff ---\033[0m\n")
                    
                    print()  # Add newline after response
                    
                    # Save output if requested
                    if output_file:
                        with open(output_file, "w") as f:
                            f.write(response_text)
                        print(f"Response saved to {output_file}")
                    
                    # Apply diff if requested
                    target_dir = None
                    if apply_to:
                        # Use the existing function to extract diff
                        diff = extract_latest_diff(events)
                        
                        if diff:
                            apply_dir = os.path.abspath(os.path.expanduser(apply_to))
                            print(f"Applying diff to {apply_dir}")
                            os.makedirs(apply_dir, exist_ok=True)
                            success, message = apply_patch(diff, apply_dir)
                            print(message)
                            
                            if success:
                                target_dir = apply_dir
                                print(f"Diff successfully applied to {target_dir}")
                            else:
                                print("Failed to apply diff")
                        else:
                            print("No diff found in response")
                    
                    # Run server if requested
                    if run and target_dir:
                        success, message = await start_server_in_directory(target_dir)
                        if success:
                            print("Server started successfully")
                            print("To stop the server later, run: docker compose down -v")
                        else:
                            print(f"Failed to start server: {message}")
                    
                    # Save state
                    if autosave:
                        previous_messages.append(message)
                        previous_events.extend(events)
                        with open(state_file, "w") as f:
                            json.dump({
                                "events": [e.model_dump() for e in previous_events],
                                "messages": previous_messages,
                                "agent_state": request.agent_state,
                                "timestamp": datetime.now().isoformat()
                            }, f, indent=2)
                            print(f"State saved to {state_file}")
                    
                    print("Task completed. Exiting.")
                    return
                
                except Exception as e:
                    print(f"Error in non-interactive mode: {e}")
                    traceback.print_exc()
                    return

    # Continue with interactive mode if not in non-interactive mode
    # Banner
    divider = "=" * 60
    print(divider)
    print("Interactive Agent CLI Chat")
    print("Type '/help' for commands.")
    print("Use an empty line to finish multi-line input.")
    print("Pipes are supported: /logs error | feedback")
    print(divider)

    if host:
        base_url = f"http://{host}:{port}"
        print(f"Connected to {base_url}")
    else:
        base_url = None # Use ASGI transport for local testing
    
    # Continue with existing interactive mode...
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
                
                # Handle piping
                if "|" in cmd:
                    pipe_segments = cmd.split("|")
                    previous_output = None
                    
                    # Process each command in the pipe
                    for i, segment in enumerate(pipe_segments):
                        segment = segment.strip()
                        if not segment:
                            print(f"Error: Empty command in pipe segment {i+1}")
                            previous_output = None
                            break
                            
                        # Extract command and args
                        parts = shlex.split(segment)
                        command, *args = parts
                        
                        # Skip anything that doesn't look like a command
                        if not command.startswith('/'):
                            print(f"Error: Expected command starting with '/' in pipe segment {i+1}")
                            previous_output = None
                            break
                            
                        # Check if command is registered
                        handler = commands.get(command)
                        if not handler:
                            print(f"Error: Unknown command '{command}' in pipe segment {i+1}")
                            previous_output = None
                            break
                            
                        try:
                            # Call the command handler with piped input
                            previous_output = await handler(
                                args, 
                                previous_output=previous_output,
                                client=client,
                                request=request,
                                previous_events=previous_events,
                                previous_messages=previous_messages,
                                settings_dict=settings_dict,
                                state_file=state_file,
                                autosave=autosave,
                                project_dir=project_dir
                            )
                            
                            # Update request if it changed
                            if command == "/feedback":
                                request = request
                        except Exception as e:
                            print(f"Error processing command '{command}': {e}")
                            traceback.print_exc()
                            previous_output = None
                            break
                    
                    # Done with pipe processing
                    continue
                
                # Check if the input starts with a command (first line)
                first_line = cmd.split('\n', 1)[0].strip()
                if first_line.startswith('/'):
                    action, *rest = first_line.split(None, 1)
                    # For commands, only use the first line
                    cmd = first_line
                else:
                    action = None
                
                # Handle using the command registry for non-piped commands
                if action and action in commands:
                    args = shlex.split(rest[0]) if rest else []
                    try:
                        await commands[action](
                            args,
                            client=client, 
                            request=request,
                            previous_events=previous_events,
                            previous_messages=previous_messages,
                            settings_dict=settings_dict,
                            state_file=state_file,
                            autosave=autosave,
                            project_dir=project_dir
                        )
                    except Exception as e:
                        print(f"Error executing command {action}: {e}")
                        traceback.print_exc()
                    continue
                    
                # Fall back to original command handling for commands not in registry
                match action.lower().strip() if action else None:
                    case "/exit" | "/quit":
                        print("Goodbye!")
                        return
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
                            
                            # Create log file BEFORE starting Docker
                            # This ensures logs are available even if Docker fails
                            global current_log_file
                            logs_dir = os.path.join(target_dir, "logs")
                            os.makedirs(logs_dir, exist_ok=True)
                            log_file = os.path.join(logs_dir, f"server_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
                            current_log_file = log_file
                            
                            # Log initial setup message
                            save_log_line(current_log_file, "Starting server setup...")
                            
                            print("Building services with Docker Compose...")
                            try:
                                # Build the services
                                build_result = subprocess.run(
                                    ["docker", "compose", "build"], 
                                    cwd=target_dir, 
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                if build_result.returncode != 0:
                                    error_msg = f"Docker Compose build failed with code {build_result.returncode}"
                                    print(f"Error: {error_msg}")
                                    save_log_line(current_log_file, error_msg)
                                    save_log_line(current_log_file, build_result.stdout)
                                    save_log_line(current_log_file, build_result.stderr)
                                    # Continue to start log reader even after error
                                else:
                                    print("Dependencies installed successfully.")
                                    save_log_line(current_log_file, "Build completed successfully")
                                
                                print("\nStarting development server with Docker Compose...")
                                save_log_line(current_log_file, "Starting Docker services...")
                                
                                # Ensure clean environment with down before starting
                                down_result = subprocess.run(
                                    ["docker", "compose", "down", "-v", "--remove-orphans"],
                                    cwd=target_dir,
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                if down_result.stdout:
                                    save_log_line(current_log_file, down_result.stdout)
                                if down_result.stderr:
                                    save_log_line(current_log_file, down_result.stderr)
                                
                                # Start the services with the environment variables set
                                result = subprocess.run(
                                    ["docker", "compose", "up", "-d"],
                                    cwd=target_dir,
                                    capture_output=True,
                                    text=True,
                                    check=False
                                )
                                
                                # Log the output regardless of success or failure
                                if result.stdout:
                                    save_log_line(current_log_file, result.stdout)
                                if result.stderr:
                                    save_log_line(current_log_file, result.stderr)
                                
                                if result.returncode != 0:
                                    print(f"Warning: Docker Compose returned non-zero exit code: {result.returncode}")
                                    error_output = f"Error output: {result.stderr}"
                                    print(error_output)
                                    save_log_line(current_log_file, f"Docker Compose error (code {result.returncode})")
                                    save_log_line(current_log_file, error_output)
                                    # Continue to start log reader even after error
                                else:
                                    print("All services started successfully.")
                                    save_log_line(current_log_file, "All services started successfully")
                                
                                # Ensure we capture ALL logs - both historical and new
                                def collect_historical_logs():
                                    """Collect all historical logs at startup to ensure nothing is missed"""
                                    try:
                                        save_log_line(current_log_file, "Collecting historical Docker logs...")
                                        # Get all logs without follow flag to capture history
                                        result = subprocess.run(
                                            ["docker", "compose", "logs", "--no-color"],
                                            cwd=target_dir,
                                            capture_output=True,
                                            text=True,
                                            check=False
                                        )
                                        if result.stdout:
                                            # Process and save all historical log lines
                                            for line in result.stdout.splitlines():
                                                save_log_line(current_log_file, line)
                                            
                                        save_log_line(current_log_file, "Historical logs collection completed")
                                    except Exception as e:
                                        save_log_line(current_log_file, f"Error collecting historical logs: {e}")
                                
                                # Start historical log collection in a separate thread
                                # This ensures we don't miss any logs from the beginning
                                hist_thread = threading.Thread(target=collect_historical_logs, daemon=True)
                                hist_thread.start()
                                
                                # Use Popen to follow the logs (for new logs)
                                current_server_process = subprocess.Popen(
                                    ["docker", "compose", "logs", "--follow", "--no-color", "--timestamps"],
                                    cwd=target_dir,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    text=True
                                )
                                
                                # Start a background thread to read logs
                                def log_reader():
                                    # Common error patterns to watch for
                                    error_patterns = [
                                        "Error:", "ERROR:", "Exception:", "EXCEPTION:",
                                        "Failed to", "failed to",
                                        "Bind for", "port is already allocated",
                                        "Connection refused",
                                        "exited with code",
                                        "Exited with code",
                                        "OCI runtime",
                                        "npm ERR!",
                                        "error Command failed",
                                        "syntax error",
                                        "Cannot start service",
                                        "denied: requested access to the resource is denied",
                                        "Permission denied"
                                    ]
                                    
                                    critical_errors_shown = set()  # Track errors we've already shown
                                    last_alert_time = time.time()  # Rate limit error alerts
                                    last_sync_time = time.time()   # Track last resync time
                                    
                                    # Periodically sync logs to catch any logs from restarted containers
                                    def resync_logs():
                                        nonlocal last_sync_time
                                        # Only resync every 30 seconds to avoid performance issues
                                        current_time = time.time()
                                        if current_time - last_sync_time < 30:
                                            return
                                            
                                        # Check if we have active containers that might have restarted
                                        try:
                                            ps_result = subprocess.run(
                                                ["docker", "compose", "ps", "--format", "json"],
                                                cwd=target_dir,
                                                capture_output=True,
                                                text=True,
                                                check=False
                                            )
                                            
                                            # If we got container list, check if any have restarted recently
                                            if ps_result.returncode == 0 and ps_result.stdout.strip():
                                                save_log_line(current_log_file, "Resyncing logs to catch any missed entries...")
                                                # Get latest logs in a single batch (last 100 lines from each container)
                                                resync_result = subprocess.run(
                                                    ["docker", "compose", "logs", "--no-color", "--tail=100"],
                                                    cwd=target_dir,
                                                    capture_output=True,
                                                    text=True,
                                                    check=False
                                                )
                                                # Only log info about the resync, not the actual logs
                                                # as they'll appear in the continuous follow
                                                if resync_result.returncode == 0:
                                                    save_log_line(current_log_file, "Log resync completed")
                                                
                                            last_sync_time = current_time
                                        except Exception as e:
                                            save_log_line(current_log_file, f"Error during log resync: {e}")
                                    
                                    while current_server_process and current_server_process.poll() is None:
                                        line = current_server_process.stdout.readline()
                                        if not line:
                                            # When there's no output, check if we need to resync
                                            # This helps catch logs after container restarts
                                            resync_logs()
                                            time.sleep(0.1)
                                            continue
                                        
                                        line_str = line.rstrip()
                                        if current_log_file:
                                            save_log_line(current_log_file, line_str)
                                        
                                        # Check for error patterns in the log line
                                        for pattern in error_patterns:
                                            if pattern in line_str:
                                                # Create a hash of the error to avoid duplicates
                                                error_hash = hash(line_str[:100])
                                                
                                                # Only show each unique error once and rate limit
                                                current_time = time.time()
                                                if (error_hash not in critical_errors_shown and 
                                                        current_time - last_alert_time > 2.0):
                                                    critical_errors_shown.add(error_hash)
                                                    last_alert_time = current_time
                                                    
                                                    # Display the error in the console
                                                    print(f"\n\033[91m🚨 SERVER ERROR DETECTED: \033[0m")
                                                    print(f"\033[91m{line_str}\033[0m")
                                                    print(f"Use '/logs' command to view full logs.")
                                                    
                                                break  # Stop checking other patterns for this line

                                # Start the log reader in a separate thread
                                log_thread = threading.Thread(target=log_reader, daemon=True)
                                log_thread.start()
                                
                                print("\nServer starting... Logs are being saved but not displayed.")
                                print(f"Full logs are saved to: {current_log_file}")
                                print("Use '/logs' command to view the logs.")
                                print("Error detection is active - critical errors will be shown automatically.")
                                
                                print("\n🌐 Web UI is available at:")
                                print("   http://localhost:80 (for web servers, default HTTP port)")
                                
                                print(f"\nServer running in {target_dir}")
                                print("Use /stop command to stop the server when done.")
                                print("Use /logs to view server logs.")
                                
                            except subprocess.CalledProcessError as e:
                                error_msg = f"Error during project setup: {e}"
                                print(error_msg)
                                save_log_line(current_log_file, error_msg)
                            except FileNotFoundError:
                                error_msg = "Error: 'docker' command not found. Please make sure Docker is installed."
                                print(error_msg)
                                save_log_line(current_log_file, error_msg)
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
                    case None:
                        # For non-command input, use the entire text including multiple lines
                        content = ui
                    case _:
                        # Check if this is an unknown command (starts with /)
                        if action.startswith('/'):
                            print(f"Unknown command: {action}")
                            print("Use /help to see available commands")
                            await handle_help([], client=client, project_dir=project_dir)
                            continue
                        else:
                            # For unknown input that doesn't start with /, treat as a message
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

def cli(
    host: str = "",
    port: int = 8001,
    state_file: str = "/tmp/agent_chat_state.json",
    settings: Optional[str] = None,
    autosave: bool = False,
    # Non-interactive mode parameters
    message: Optional[str] = None,
    apply_to: Optional[str] = None,
    run: bool = False,
    output_file: Optional[str] = None
):
    """
    Launch the chatbot client.
    
    Args:
        host: API host (default: empty for local ASGI)
        port: API port (default: 8001)
        state_file: Path to state file for saving/loading conversations (default: /tmp/agent_chat_state.json)
        settings: JSON string with settings (default: None)
        autosave: Whether to autosave state after each message (default: False)
        
        # Non-interactive mode:
        message: Message to send to agent (enables non-interactive mode)
        apply_to: Directory to apply any diff to
        run: Whether to run the server after applying diff
        output_file: File to save agent's response to
    """
    anyio.run(
        run_chatbot_client, 
        host, 
        port, 
        state_file, 
        settings, 
        autosave, 
        message, 
        apply_to, 
        run, 
        output_file
    )

if __name__ == "__main__":
    try:
        import coloredlogs
        coloredlogs.install(level="INFO")
    except ImportError:
        pass

    from fire import Fire
    Fire(cli)
