"""
Simple mock agent implementation for API testing.

This mock agent mimics the real agent's behavior by:
1. Generating an initial app on the first request
2. Making minor modifications on subsequent requests
3. Maintaining state between calls
"""
import hashlib
from typing import Dict, Any, Optional

from api.agent_server.interface import AgentInterface
from api.agent_server.models import AgentSseEvent, AgentMessage, AgentStatus, MessageKind

from log import get_logger

logger = get_logger(__name__)


class SimpleMockAgent(AgentInterface):
    """
    Simple mock agent that generates an app and makes minor changes.
    """
    
    # Base template for a simple counter app
    BASE_TEMPLATE = """diff --git a/server/index.js b/server/index.js
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/server/index.js
@@ -0,0 +1,20 @@
+const express = require('express');
+const app = express();
+let counter = 0;
+
+app.get('/api/counter', (req, res) => {
+  res.json({ count: counter });
+});
+
+app.post('/api/counter/increment', (req, res) => {
+  counter++;
+  res.json({ count: counter });
+});
+
+app.listen(3000);
diff --git a/frontend/index.html b/frontend/index.html
new file mode 100644
index 0000000..2345678
--- /dev/null
+++ b/frontend/index.html
@@ -0,0 +1,15 @@
+<!DOCTYPE html>
+<html>
+<head>
+  <title>Counter App</title>
+</head>
+<body>
+  <h1>Counter: <span id="count">0</span></h1>
+  <button onclick="increment()">Click Me</button>
+  <script>
+    function increment() {
+      fetch('/api/counter/increment', {method: 'POST'})
+        .then(r => r.json())
+        .then(data => document.getElementById('count').textContent = data.count);
+    }
+  </script>
+</body>
+</html>"""

    # Simple modifications to apply in sequence
    MODIFICATIONS = [
        # Add emoji
        {
            "description": "Adding emoji to make it fun",
            "diff": """diff --git a/frontend/index.html b/frontend/index.html
index 2345678..3456789 100644
--- a/frontend/index.html
+++ b/frontend/index.html
@@ -4,7 +4,7 @@
   <title>Counter App</title>
 </head>
 <body>
-  <h1>Counter: <span id="count">0</span></h1>
+  <h1>🎯 Counter: <span id="count">0</span> 🎉</h1>
   <button onclick="increment()">Click Me</button>
   <script>"""
        },
        # Add reset button
        {
            "description": "Adding reset functionality",
            "diff": """diff --git a/frontend/index.html b/frontend/index.html
index 3456789..4567890 100644
--- a/frontend/index.html
+++ b/frontend/index.html
@@ -6,6 +6,7 @@
 <body>
   <h1>🎯 Counter: <span id="count">0</span> 🎉</h1>
   <button onclick="increment()">Click Me</button>
+  <button onclick="reset()">Reset</button>
   <script>
     function increment() {
       fetch('/api/counter/increment', {method: 'POST'})
@@ -13,6 +14,11 @@
         .then(data => document.getElementById('count').textContent = data.count);
     }
+    function reset() {
+      fetch('/api/counter/reset', {method: 'POST'})
+        .then(r => r.json())
+        .then(data => document.getElementById('count').textContent = data.count);
+    }
   </script>
 </body>"""
        },
        # Add styling
        {
            "description": "Adding some styling",
            "diff": """diff --git a/frontend/index.html b/frontend/index.html
index 4567890..5678901 100644
--- a/frontend/index.html
+++ b/frontend/index.html
@@ -2,6 +2,13 @@
 <html>
 <head>
   <title>Counter App</title>
+  <style>
+    body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
+    button { padding: 10px 20px; margin: 5px; font-size: 16px; cursor: pointer; }
+    button:hover { background-color: #f0f0f0; }
+    #count { color: #007bff; font-weight: bold; }
+  </style>
 </head>
 <body>"""
        }
    ]

    def __init__(self, application_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        self.application_id = application_id
        self.trace_id = trace_id
        self.settings = settings or {}
        self.state = {
            "iteration": 0,
            "initialized": False
        }

    async def process(self, request, event_sender):
        """Process request and generate appropriate response."""
        try:
            logger.info(f"Mock agent processing request for {self.application_id}:{self.trace_id}")
            
            # Restore state if provided
            if request.agent_state:
                self.state = request.agent_state
            
            # Simulate some processing stages
            await event_sender.send(AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.STAGE_RESULT,
                    content="Analyzing request...",
                    agentState=self.state,
                    unifiedDiff=None
                )
            ))
            
            # Determine what to generate
            if not self.state.get("initialized"):
                # First request - generate base app
                unified_diff = self.BASE_TEMPLATE
                message = "Generated a simple counter application with frontend and backend."
                self.state["initialized"] = True
            else:
                # Subsequent requests - apply modifications
                mod_index = self.state["iteration"] % len(self.MODIFICATIONS)
                modification = self.MODIFICATIONS[mod_index]
                unified_diff = modification["diff"]
                message = modification["description"]
                self.state["iteration"] += 1
            
            # Send another stage update
            await event_sender.send(AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.STAGE_RESULT,
                    content="Generating code changes...",
                    agentState=self.state,
                    unifiedDiff=None
                )
            ))
            
            # Generate a simple hash for the diff
            diff_hash = hashlib.sha256(unified_diff.encode()).hexdigest()[:8]
            
            # Send final result
            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.REVIEW_RESULT,
                    content=message,
                    agentState=self.state,
                    unifiedDiff=unified_diff,
                    completeDiffHash=diff_hash,
                    appName="simple-counter-app",
                    commitMessage=f"feat: {message.lower()}"
                )
            ))
            
        except Exception as e:
            logger.exception(f"Error in mock agent: {str(e)}")
            await event_sender.send(AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Mock agent error: {str(e)}",
                    agentState=self.state,
                    unifiedDiff=None
                )
            ))
        finally:
            await event_sender.aclose()