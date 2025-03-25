#!/bin/bash
# MCP Server launcher script
# Exposes tools from agent/policies/experimental.py as an MCP server
# For use with Claude Desktop or other MCP clients
# Communicates via stdin (configured in mcp_server.py)

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

LOG_FILE="/tmp/mcp.log"
# Clear the log file
> "$LOG_FILE"

# Log startup information
echo "=== $(date): Starting MCP server ===" >> "$LOG_FILE" 2>&1

# Run the MCP server directly
# Redirects stderr to log file while keeping stdout clean for MCP protocol messages
PYTHONPATH=$PYTHONPATH:./agent/ uv run python ../agent/api/mcp_server.py 2>> "$LOG_FILE"
