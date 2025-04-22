"""
Implementation of the TemplateDiffAgentImplementation for generating applications
with unified diffs. This implementation specializes in creating counter applications
with detailed logging and error handling.
"""
import os
import json
import tempfile
import shutil
from typing import Dict, Any, Optional, Tuple

from api.agent_server.interface import AgentInterface
from api.agent_server.models import AgentSseEvent, AgentMessage, AgentStatus, MessageKind

from log import get_logger

logger = get_logger(__name__)


class TemplateDiffAgentImplementation(AgentInterface):
    """
    Agent implementation that generates a counter application with unified diffs.

    This implementation demonstrates how to create a simple application with
    server and frontend components, providing unified diffs for the changes.
    """

    def __init__(self, application_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the TemplateDiffAgentImplementation.

        Args:
            application_id: Unique identifier for the application
            trace_id: Trace ID for tracking the request
            settings: Optional settings for the agent
        """
        self.application_id = application_id
        self.trace_id = trace_id
        self.settings = settings or {}
        self.state = {}
        self.temp_dir = tempfile.mkdtemp(prefix="template_diff_")
        logger.info(f"Created temporary directory: {self.temp_dir}")

    async def process(self, request, event_sender):
        """
        Process the agent request and generate a counter application.

        Args:
            request: The agent request containing messages and context
            event_sender: Channel to send events back to the client
        """
        try:
            logger.info(f"Processing request for application {self.application_id}, trace {self.trace_id}")

            user_message = request.all_messages[-1].content if request.all_messages else "Create a counter app"

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Starting counter app generation...",
                    agentState=self.state,
                    unifiedDiff=""
                )
            ))

            server_files, frontend_files, unified_diff = self._generate_counter_app(user_message)

            self._save_files(server_files, frontend_files)

            self.state = {
                "app_type": "counter",
                "files_generated": len(server_files) + len(frontend_files),
                "server_files": list(server_files.keys()),
                "frontend_files": list(frontend_files.keys()),
                "temp_dir": self.temp_dir
            }

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content=f"Counter application generated successfully with {len(server_files)} server files and {len(frontend_files)} frontend files.",
                    agentState=self.state,
                    unifiedDiff=unified_diff
                )
            ))

        except Exception as e:
            logger.exception(f"Error processing request: {str(e)}")

            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error generating counter application: {str(e)}",
                    agentState=self.state,
                    unifiedDiff=""
                )
            ))

        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            await event_sender.aclose()


    def _generate_counter_app(self, user_message: str) -> Tuple[Dict[str, str], Dict[str, str], str]:
        """
        Generate a counter application based on the user message.

        Args:
            user_message: The user's request message

        Returns:
            Tuple containing server files, frontend files, and unified diff
        """
        logger.info(f"Generating counter app based on: {user_message}")

        server_files = {
            "app.py": """from flask import Flask, jsonify, request
from flask_cors import CORS
app = Flask(__name__)
CORS(app)
counter = 0
@app.route('/api/counter', methods=['GET'])
def get_counter():
    global counter
    return jsonify({"value": counter})
@app.route('/api/counter/increment', methods=['POST'])
def increment_counter():
    global counter
    counter += 1
    return jsonify({"value": counter})
@app.route('/api/counter/decrement', methods=['POST'])
def decrement_counter():
    global counter
    counter -= 1
    return jsonify({"value": counter})
@app.route('/api/counter/reset', methods=['POST'])
def reset_counter():
    global counter
    counter = 0
    return jsonify({"value": counter})
if __name__ == '__main__':
    app.run(debug=True)
""",
            "requirements.txt": """flask==2.0.1
flask-cors==3.0.10
"""
        }

        frontend_files = {
            "index.html": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Counter App</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">
        <h1>Counter App</h1>
        <div class="counter-display">
            <span id="counter-value">0</span>
        </div>
        <div class="counter-controls">
            <button id="decrement-btn">-</button>
            <button id="reset-btn">Reset</button>
            <button id="increment-btn">+</button>
        </div>
    </div>
    <script src="app.js"></script>
</body>
</html>
""",
            "styles.css": """body {
    font-family: Arial, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    margin: 0;
    background-color: #f5f5f5;
}
.container {
    text-align: center;
    background-color: white;
    padding: 2rem;
    border-radius: 8px;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}
.counter-display {
    font-size: 4rem;
    margin: 1rem 0;
}
.counter-controls {
    display: flex;
    justify-content: center;
    gap: 1rem;
}
button {
    font-size: 1.5rem;
    padding: 0.5rem 1rem;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    transition: background-color 0.3s;
}
    background-color: #4caf50;
    color: white;
}
    background-color: #f44336;
    color: white;
}
    background-color: #2196f3;
    color: white;
}
button:hover {
    opacity: 0.9;
}
""",
            "app.js": """document.addEventListener('DOMContentLoaded', () => {
    const counterValue = document.getElementById('counter-value');
    const incrementBtn = document.getElementById('increment-btn');
    const decrementBtn = document.getElementById('decrement-btn');
    const resetBtn = document.getElementById('reset-btn');

    // API URL - change this to match your server
    const API_URL = 'http://localhost:5000/api/counter';

    // Function to update the counter display
    const updateCounter = async () => {
        try {
            const response = await fetch(API_URL);
            const data = await response.json();
            counterValue.textContent = data.value;
        } catch (error) {
            console.error('Error fetching counter:', error);
        }
    };

    // Initialize counter
    updateCounter();

    // Event listeners for buttons
    incrementBtn.addEventListener('click', async () => {
        try {
            await fetch(`${API_URL}/increment`, { method: 'POST' });
            updateCounter();
        } catch (error) {
            console.error('Error incrementing counter:', error);
        }
    });

    decrementBtn.addEventListener('click', async () => {
        try {
            await fetch(`${API_URL}/decrement`, { method: 'POST' });
            updateCounter();
        } catch (error) {
            console.error('Error decrementing counter:', error);
        }
    });

    resetBtn.addEventListener('click', async () => {
        try {
            await fetch(`${API_URL}/reset`, { method: 'POST' });
            updateCounter();
        } catch (error) {
            console.error('Error resetting counter:', error);
        }
    });
});
"""
        }

        unified_diff = self._generate_unified_diff(server_files, frontend_files)

        return server_files, frontend_files, unified_diff

    def _generate_unified_diff(self, server_files: Dict[str, str], frontend_files: Dict[str, str]) -> str:
        """
        Generate a unified diff for the created files.

        Args:
            server_files: Dictionary of server file names to content
            frontend_files: Dictionary of frontend file names to content

        Returns:
            Unified diff string
        """
        diff_lines = []

        for filename, content in server_files.items():
            diff_lines.append(f"diff --git a/server/{filename} b/server/{filename}")
            diff_lines.append("new file mode 100644")
            diff_lines.append(f"index 0000000..{hash(content) & 0xFFFFFF:x}")
            diff_lines.append("--- /dev/null")
            diff_lines.append(f"+++ b/server/{filename}")
            diff_lines.append(f"@@ -0,0 +1,{content.count(chr(10)) + 1} @@")

            for line in content.split('\n'):
                diff_lines.append(f"+{line}")

        for filename, content in frontend_files.items():
            diff_lines.append(f"diff --git a/frontend/{filename} b/frontend/{filename}")
            diff_lines.append("new file mode 100644")
            diff_lines.append(f"index 0000000..{hash(content) & 0xFFFFFF:x}")
            diff_lines.append("--- /dev/null")
            diff_lines.append(f"+++ b/frontend/{filename}")
            diff_lines.append(f"@@ -0,0 +1,{content.count(chr(10)) + 1} @@")

            for line in content.split('\n'):
                diff_lines.append(f"+{line}")

        return '\n'.join(diff_lines)

    def _save_files(self, server_files: Dict[str, str], frontend_files: Dict[str, str]) -> None:
        """
        Save the generated files to the temporary directory.

        Args:
            server_files: Dictionary of server file names to content
            frontend_files: Dictionary of frontend file names to content
        """
        server_dir = os.path.join(self.temp_dir, "server")
        os.makedirs(server_dir, exist_ok=True)

        for filename, content in server_files.items():
            file_path = os.path.join(server_dir, filename)
            with open(file_path, "w") as f:
                f.write(content)
            logger.info(f"Saved server file: {file_path}")

        frontend_dir = os.path.join(self.temp_dir, "frontend")
        os.makedirs(frontend_dir, exist_ok=True)

        for filename, content in frontend_files.items():
            file_path = os.path.join(frontend_dir, filename)
            with open(file_path, "w") as f:
                f.write(content)
            logger.info(f"Saved frontend file: {file_path}")

        metadata = {
            "server_files": list(server_files.keys()),
            "frontend_files": list(frontend_files.keys()),
            "timestamp": os.path.getmtime(self.temp_dir)
        }

        metadata_path = os.path.join(self.temp_dir, "metadata.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved metadata: {metadata_path}")
