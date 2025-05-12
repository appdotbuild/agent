import os
import shutil
import tempfile
import traceback
from typing import Tuple, Dict, Optional
import logging

# Assuming patch_ng is installed and provides PatchSet
# If not, this import will fail. Consider adding error handling or ensuring dependency.
try:
    from patch_ng import PatchSet, patch_stream
    PATCH_NG_AVAILABLE = True
except ImportError:
    PatchSet = None # Define as None if not available
    patch_stream = None
    PATCH_NG_AVAILABLE = False
    # Consider logging a warning here if patch functionality is critical
    # import logging
    # logging.warning("patch_ng library not found. Patch application functionality will be disabled.")


def apply_patch(diff: str, target_dir: str) -> Tuple[bool, str]:
    """
    Applies a unified diff patch to a target directory.

    Creates the target directory if it doesn't exist.
    Uses the `patch_ng` library to apply the patch. Handles git-style paths.
    Copies necessary template files before applying the patch for context, then
    materializes symlinks to avoid modifying original template files.

    Args:
        diff: The unified diff string.
        target_dir: The path to the directory where the patch should be applied.

    Returns:
        A tuple containing:
        - bool: True if the patch applied successfully, False otherwise.
        - str: A message indicating the result or error.
    """
    if not PATCH_NG_AVAILABLE:
        return False, "Error: patch_ng library is not installed. Cannot apply patch."

    original_dir = os.getcwd()
    try:
        print(f"Preparing to apply patch to directory: '{target_dir}'")
        target_dir = os.path.abspath(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        # Write the diff to a temporary file for patch_ng
        # Use delete=False and manually delete later to ensure it's accessible across calls
        with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, encoding='utf-8') as tmp:
            tmp.write(diff)
            tmp_path = tmp.name
            print(f"Wrote patch to temporary file: {tmp_path}")

        # --- Start: Template File Handling (Adapted from agent_api_client.py logic) ---
        # This section aims to provide context for the patch by copying relevant template files.
        # It needs careful review based on the exact project structure and template location.

        # First detect all target paths from the patch
        file_paths = []
        try:
            with open(tmp_path, 'rb') as patch_file_rb: # Open in binary for PatchSet
                patch_set = PatchSet(patch_file_rb)
                for item in patch_set.items:
                    # Decode the target paths and extract them
                    target_path = None
                    if item.target and item.target != b'/dev/null':
                        target_path = item.target.decode('utf-8', errors='ignore')
                        if target_path.startswith('b/'): # Remove prefix from git style patches
                            target_path = target_path[2:]
                    elif item.source and item.source != b'/dev/null': # Handle cases where only source exists (e.g., file deletion)
                        target_path = item.source.decode('utf-8', errors='ignore')
                        if target_path.startswith('a/'):
                            target_path = target_path[2:]
                    
                    if target_path:
                        file_paths.append(target_path)
        except Exception as parse_err:
             # It's possible patch_ng fails to parse; proceed without pre-copying if so.
             print(f"Warning: Could not parse patch file to pre-determine file paths: {parse_err}")
             file_paths = [] # Reset file_paths if parsing failed

        # Define template root relative to *this* file's location or use an absolute/configurable path.
        # Assuming diff_utils.py is in agent/core/, the template might be ../trpc_agent/template
        # THIS PATH IS CRITICAL AND MIGHT NEED ADJUSTMENT
        template_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../trpc_agent/template")
        )

        if os.path.isdir(template_root) and file_paths:
            print(f"Copying relevant files from template ({template_root}) to target ({target_dir}) for patch context.")

            # Copy only the files mentioned in the patch from the template, if they exist.
            # This is safer than copying the whole template.
            copied_count = 0
            for rel_path in file_paths:
                template_file = os.path.join(template_root, rel_path)
                dest_file = os.path.join(target_dir, rel_path)
                dest_dir = os.path.dirname(dest_file)

                if os.path.isfile(template_file):
                    try:
                        if not os.path.exists(dest_dir):
                            os.makedirs(dest_dir)
                        if not os.path.exists(dest_file): # Avoid overwriting files already present in target_dir
                            shutil.copy2(template_file, dest_file)
                            copied_count += 1
                            # print(f"  ↳ copied template file {rel_path}") # Optional: verbose logging
                    except Exception as cp_err:
                        print(f"Warning: could not copy template file {rel_path}: {cp_err}")
            if copied_count > 0:
                print(f"Copied {copied_count} files from template for context.")

        else:
            if not os.path.isdir(template_root):
                 print(f"Warning: Template directory not found at {template_root}. Skipping template file copying.")
            # No need to print if file_paths is empty

        # --- End: Template File Handling ---

        # Change directory to apply the patch correctly relative to target files
        os.chdir(target_dir)
        print(f"Changed directory to: {target_dir}")

        # Apply the patch using patch_ng stream function
        success = False
        stderr_output = ""
        try:
            # Use patch_stream for applying from file
            with open(tmp_path, 'rb') as patch_file_to_apply:
                 # patch_stream expects binary stream
                 result = patch_stream(patch_file_to_apply, root=target_dir) # Apply in the target dir
                 success = result # patch_stream returns True on success, False otherwise
                 # patch_stream doesn't provide stderr directly, rely on exceptions mostly

            if success:
                print("Patch applied successfully according to patch_stream.")
                # Optional: Verify changes or check for .rej files if needed
            else:
                # patch_stream returning False usually indicates failed hunks
                # .rej files might have been created.
                print("Patch application failed or had rejects according to patch_stream.")
                # Attempt to find .rej files for more info (optional)
                reject_files = [f for f in os.listdir(target_dir) if f.endswith('.rej')]
                if reject_files:
                    stderr_output = f"Patch application failed. Reject files found: {', '.join(reject_files)}"
                    print(stderr_output)
                else:
                    stderr_output = "Patch application failed for unknown reasons (no reject files found)."
                    print(stderr_output)

        except Exception as patch_err:
             success = False
             stderr_output = f"Error during patch application process: {patch_err}"
             print(stderr_output)
             traceback.print_exc() # Print traceback for debugging

        # Construct result message
        if success:
            message = f"Successfully applied the patch to the directory '{target_dir}'"
        else:
            message = f"Failed to apply the patch to '{target_dir}'. Details: {stderr_output}"

        return success, message

    except Exception as e:
        # General exception handling for setup/teardown issues
        print(f"An unexpected error occurred in apply_patch: {e}")
        traceback.print_exc()
        return False, f"Error setting up patch application: {str(e)}"
    finally:
        # Ensure we change back to the original directory
        os.chdir(original_dir)
        # Clean up the temporary patch file
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                print(f"Cleaned up temporary patch file: {tmp_path}")
            except Exception as clean_err:
                print(f"Warning: Failed to clean up temporary patch file {tmp_path}: {clean_err}")

# Example usage (optional, for testing within this file)
# if __name__ == "__main__":
#     # Create dummy files and a patch for testing
#     test_dir = "patch_test_target"
#     template_dir = "patch_test_template"
#     os.makedirs(os.path.join(template_dir, "subdir"), exist_ok=True)
#     with open(os.path.join(template_dir, "file1.txt"), "w") as f:
#         f.write("Line 1\\nLine 2\\n")
#     with open(os.path.join(template_dir, "subdir", "file2.txt"), "w") as f:
#         f.write("Original content\\n")

#     # Sample diff (modify file1.txt, add file3.txt)
#     sample_diff = """--- a/file1.txt
# +++ b/file1.txt
# @@ -1,2 +1,2 @@
#  Line 1
# -Line 2
# +Line Two
# --- /dev/null
# +++ b/subdir/file3.txt
# @@ -0,0 +1 @@
# +This is a new file.
# """
#     # Adjust template root path based on where this script is run if using relative paths
#     # For this example, assume template_dir is adjacent
#     # Note: The copy logic in apply_patch needs the template_root variable correctly set
#     # relative to diff_utils.py or made absolute/configurable.

#     print(f"Running apply_patch test...")
#     # Manually adjust template_root for test or ensure test setup reflects expected structure
#     # This example might fail if template_root isn't correctly pointing to patch_test_template
#     # relative to the execution location of this test block.
#     # It's generally better to run tests using a test framework like pytest.
#     # success, msg = apply_patch(sample_diff, test_dir)
#     # print(f"Result: {success} - {msg}")

#     # # Clean up test directories
#     # import time
#     # time.sleep(1) # Allow FS time to release handles potentially
#     # if os.path.exists(test_dir):
#     #     shutil.rmtree(test_dir)
#     # if os.path.exists(template_dir):
#     #      shutil.rmtree(template_dir) 

# Import necessary components for generate_diff
import dagger
from dagger import Directory # Explicitly import Directory if used directly
from .workspace import Workspace # Fix: Use relative import for Workspace

logger = logging.getLogger(__name__)

async def generate_diff(
    current_files: Dict[str, str],
    base_context: Directory,
    snapshot_files: Optional[Dict[str, str]] = None
) -> str:
    """
    Generates a unified diff between a base state (defined by base_context and snapshot_files)
    and a final state (defined by current_files) using a Dagger container with git.

    Args:
        current_files: A dictionary mapping file paths to their content for the final state.
        base_context: A Dagger Directory representing the initial filesystem state (e.g., from a template dir or empty).
        snapshot_files: Optional dictionary mapping file paths to content, representing files
                        present in a previous state, to be layered onto the base_context.

    Returns:
        A string containing the unified diff, or an empty string if no changes.
    """
    logger.info(f"Generating diff. Comparing {len(current_files)} current files against base context and {len(snapshot_files or {})} snapshot files.")

    # Prepare the initial context by layering snapshot files onto the base context
    initial_context = base_context
    if snapshot_files:
        for file_path, file_content in snapshot_files.items():
            initial_context = initial_context.with_new_file(file_path, file_content)
            logger.debug(f"Added snapshot file {file_path} to initial context.")

    try:
        # Create a workspace initialized with the combined initial context.
        # Using "alpine/git" as the base image for git commands.
        workspace = await Workspace.create(base_image="alpine/git", context=initial_context)

        # Write the current files to the workspace, representing the final state.
        if not current_files:
             logger.warning("generate_diff called with no current_files. Diff will likely be empty or show deletions relative to base.")
        for file_path, file_content in current_files.items():
            # Use force=True in write_file if Workspace has protections that might interfere,
            # otherwise, rely on default permissions or configure Workspace permissions appropriately.
            workspace.write_file(file_path, file_content)
            logger.debug(f"Wrote current file {file_path} to workspace.")

        # Generate the diff using the Workspace's diff method.
        # This method handles git initialization and diffing against the initial state (self.start).
        diff_output = await workspace.diff()
        logger.info(f"Generated diff of length {len(diff_output)}")
        return diff_output

    except Exception as e:
        logger.exception("Error during diff generation process in generate_diff")
        # Depending on desired behavior, either raise the exception or return an error indicator/empty string.
        # Returning an empty string might hide errors, consider re-raising or returning a specific error value.
        # raise # Option 1: Propagate the error
        return f"# Error generating diff: {e}" # Option 2: Return error marker in diff string 