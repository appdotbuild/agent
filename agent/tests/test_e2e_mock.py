import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock
from api.agent_server.models import AgentSseEvent, AgentMessage, AgentStatus
from api.agent_server.agent_api_client import latest_unified_diff, DEFAULT_APP_REQUEST

# Mock diff content for testing
MOCK_DIFF = """diff --git a/index.html b/index.html
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/index.html
@@ -0,0 +1,25 @@
+<!DOCTYPE html>
+<html lang="en">
+<head>
+    <meta charset="UTF-8">
+    <meta name="viewport" content="width=device-width, initial-scale=1.0">
+    <title>Click Counter</title>
+    <style>
+        body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
+        button { padding: 10px 20px; font-size: 16px; cursor: pointer; }
+        #counter { font-size: 24px; margin: 20px 0; }
+    </style>
+</head>
+<body>
+    <h1>Button Click Counter</h1>
+    <div id="counter">0</div>
+    <button id="clickButton">Click Me!</button>
+
+    <script>
+        document.addEventListener('DOMContentLoaded', () => {
+            const counterElement = document.getElementById('counter');
+            const button = document.getElementById('clickButton');
+            let count = 0;
+            
+            button.addEventListener('click', () => {
+                count++;
+                counterElement.textContent = count;
+            });
+        });
+    </script>
+</body>
+</html>"""

# Create mock events with the diff
def create_mock_events():
    mock_message = AgentMessage.model_validate({
        "content": "Mock response for testing",
        "unifiedDiff": MOCK_DIFF,
        "kind": "StageResult"
    })
    mock_event = AgentSseEvent(
        status=AgentStatus.IDLE,
        trace_id="mock-trace-id",
        message=mock_message
    )
    return [mock_event]

# Mock for AgentApiClient
class MockAgentApiClient:
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
        
    async def send_message(self, prompt):
        events = create_mock_events()
        request = MagicMock()
        return events, request
