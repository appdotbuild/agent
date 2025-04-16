#!/usr/bin/env python3
import json
import os
from pathlib import Path

def setup_global_mcp():
    # Get absolute path to run_mcp.sh
    script_dir = Path(__file__).resolve().parent.parent

    # Path to project MCP config; could be replaced with global config instead
    global_mcp_path = script_dir / ".cursor" / "mcp.json"
    run_mcp_path = script_dir / "mcp_tools" / "run_mcp.sh"

    # Ensure run_mcp.sh is executable
    os.chmod(run_mcp_path, 0o755)

    # Create or load existing global MCP config
    if global_mcp_path.exists():
        try:
            with open(global_mcp_path, "r") as f:
                mcp_config = json.load(f)
        except json.JSONDecodeError:
            mcp_config = {"mcpServers": {}}
    else:
        # Ensure parent directory exists
        global_mcp_path.parent.mkdir(exist_ok=True)
        mcp_config = {"mcpServers": {}}

    # Add or update our MCP server config
    mcp_config["mcpServers"]["app-build"] = {
        "command": str(run_mcp_path),
        "args": []
    }

    # Save the config
    with open(global_mcp_path, "w") as f:
        json.dump(mcp_config, f, indent=2)

    print(f"Updated global MCP config at {global_mcp_path}")
    print(f"Added 'app-build' server with command: {run_mcp_path}")

if __name__ == "__main__":
    setup_global_mcp()
