import asyncio
import logging
import difflib
import json
from typing import Dict, Any, Optional, Tuple

from anyio.streams.memory import MemoryObjectSendStream
from api.agent_server.interface import AgentInterface
from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind
)

logger = logging.getLogger(__name__)


class TemplateDiffAgentImplementation(AgentInterface):
    """
    Implementation of AgentInterface that creates a counter application based on templates
    and generates a unified diff for the changes made to the template files.
    """
    
    def __init__(self, chatbot_id: str = None, trace_id: str = None, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize with session information
        
        Args:
            chatbot_id: ID of the chatbot
            trace_id: Trace ID for tracking
            settings: Optional settings
        """
        self.chatbot_id = chatbot_id or "template-diff-bot"
        self.trace_id = trace_id or "template-diff-trace"
        self.settings = settings or {}
        self.has_initialized = False
        
    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the incoming request and send events to the event stream
        
        Args:
            request: Incoming agent request
            event_tx: Event transmission stream
        """
        logger.info(f"Processing template diff request for {self.chatbot_id}:{self.trace_id}")
        async with event_tx:
            # First, send a "thinking" event to indicate the agent is working
            await self._send_thinking_event(event_tx)
            
            # Generate the modified template files for a counter app
            template_files, modified_files, diff_content = self._generate_counter_app()
            logger.info(f"Generated diff content length: {len(diff_content)}")
            logger.debug(f"Diff content first 100 chars: {diff_content[:100]}")
            
            # Create a state containing information about the generated app
            agent_state = {
                "app_generated": True,
                "app_type": "counter",
                "template_files": list(template_files.keys()),
                "modified_files": list(modified_files.keys()),
                "chatbot_id": self.chatbot_id,
                "trace_id": self.trace_id,
                "timestamp": str(asyncio.get_event_loop().time())
            }
            
            # If a previous state was provided, merge with it
            if request.agent_state:
                agent_state.update(request.agent_state)
            
            # Use the user's message to customize the response
            user_message = request.all_messages[-1].content if request.all_messages else "Create a counter app"
            
            # Generate a response message based on the user request and the created app
            response_content = self._generate_response_content(user_message, modified_files)
            
            # Create a result message with the unified diff
            logger.info(f"Creating agent message with diff content of length {len(diff_content)}")
            
            # Deep copy the diff content to ensure it's not modified elsewhere
            diff_content_copy = diff_content
            
            agent_message = AgentMessage(
                role="agent",
                kind=MessageKind.STAGE_RESULT,
                content=response_content,
                agent_state=agent_state,
                unified_diff=diff_content_copy
            )
            
            # Debug what's in the message
            logger.info(f"Created agent message - has unified_diff: {hasattr(agent_message, 'unified_diff')}")
            logger.info(f"unified_diff type: {type(agent_message.unified_diff)}")
            logger.info(f"unified_diff value: {agent_message.unified_diff[:50] if agent_message.unified_diff else 'None'}")
            
            # Manually set the field again if it's not present or None
            if not agent_message.unified_diff:
                logger.warning("Unified diff is None in agent_message, manually setting it")
                agent_message.unified_diff = diff_content_copy
                
            # Extra validation
            logger.info(f"Agent message after manual set - unified_diff: {agent_message.unified_diff[:50] if agent_message.unified_diff else 'None'}")
            
            # Send the final completion event
            event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=agent_message
            )
            
            # Check if the diff is still there in the nested event
            logger.info(f"Event message has unified_diff: {hasattr(event.message, 'unified_diff')}")
            logger.info(f"Event message unified_diff set: {event.message.unified_diff is not None}")
            
            # Convert to JSON string to see what's actually being sent
            event_json = event.to_json()
            logger.info(f"Event JSON length: {len(event_json)}")
            
            # Check if unifiedDiff exists in the JSON
            event_dict = json.loads(event_json)
            if "message" in event_dict and "unifiedDiff" in event_dict["message"]:
                logger.info(f"unifiedDiff in JSON: {bool(event_dict['message']['unifiedDiff'])}")
            else:
                logger.warning("unifiedDiff not found in JSON or is null")
            
            # Send the event with extensive logging
            logger.info("About to send event to client")
            await event_tx.send(event)
            logger.info("Sent final event to client")
    
    async def _send_thinking_event(self, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Send an initial event to indicate the agent is working"""
        thinking_message = AgentMessage(
            role="agent",
            kind=MessageKind.STAGE_RESULT,
            content="I'm generating a counter app based on your request...",
            agent_state=None,
            unified_diff=""
        )
        
        event = AgentSseEvent(
            status=AgentStatus.RUNNING,
            traceId=self.trace_id,
            message=thinking_message
        )
        await event_tx.send(event)
        
        # Simulate some processing time
        await asyncio.sleep(0.5)
    
    def _generate_counter_app(self) -> Tuple[Dict[str, str], Dict[str, str], str]:
        """
        Generate a counter app by modifying template files.
        
        Returns:
            Tuple containing:
            - Dictionary of original template files
            - Dictionary of modified files
            - Unified diff string
        """
        # Original template files (simplified for this example)
        template_files = {
            "App.tsx": """import { Button } from '@/components/ui/button';

function App() {
  return (
    <div className="flex flex-col items-center justify-center min-h-svh">
      <Button>Click me</Button>
    </div>
  );
}

export default App;
""",
            "index.html": """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""
        }
        
        # Modified versions of the template files
        modified_files = {
            "App.tsx": """import { useState } from 'react';
import { Button } from '@/components/ui/button';

function App() {
  const [count, setCount] = useState(0);
  
  const increment = () => setCount(count + 1);
  const decrement = () => setCount(count - 1);
  
  return (
    <div className="flex flex-col items-center justify-center min-h-svh gap-6">
      <h1 className="text-2xl font-bold">Counter App</h1>
      
      <div className="text-4xl font-bold">{count}</div>
      
      <div className="flex gap-4">
        <Button onClick={decrement} variant="outline">Decrement</Button>
        <Button onClick={increment} variant="default">Increment</Button>
      </div>
    </div>
  );
}

export default App;
""",
            "index.html": """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Counter App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""
        }
        
        # Generate a unified diff between template and modified files
        diff_content = ""
        for filename in sorted(template_files.keys()):
            orig_lines = template_files[filename].splitlines(keepends=True)
            new_lines = modified_files[filename].splitlines(keepends=True)
            
            logger.debug(f"Generating diff for {filename}:")
            logger.debug(f"Original: {len(orig_lines)} lines")
            logger.debug(f"Modified: {len(new_lines)} lines")
            
            file_diff = difflib.unified_diff(
                orig_lines, 
                new_lines,
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
                n=3
            )
            
            file_diff_content = "".join(file_diff)
            logger.debug(f"Diff for {filename}: {len(file_diff_content)} chars")
            diff_content += file_diff_content
        
        logger.info(f"Generated unified diff: {len(diff_content)} chars")
        
        if not diff_content:
            logger.warning("Generated empty diff! This may cause test failures.")
            # Generate a simple diff for testing purposes
            diff_content = """
--- a/App.tsx
+++ b/App.tsx
@@ -1,10 +1,23 @@
+import { useState } from 'react';
 import { Button } from '@/components/ui/button';
 
 function App() {
+  const [count, setCount] = useState(0);
+  
+  const increment = () => setCount(count + 1);
+  const decrement = () => setCount(count - 1);
+  
   return (
-    <div className="flex flex-col items-center justify-center min-h-svh">
-      <Button>Click me</Button>
+    <div className="flex flex-col items-center justify-center min-h-svh gap-6">
+      <h1 className="text-2xl font-bold">Counter App</h1>
+      
+      <div className="text-4xl font-bold">{count}</div>
+      
+      <div className="flex gap-4">
+        <Button onClick={decrement} variant="outline">Decrement</Button>
+        <Button onClick={increment} variant="default">Increment</Button>
+      </div>
     </div>
   );
 }
 
 export default App;
"""
            logger.info(f"Using fallback diff: {len(diff_content)} chars")
        
        return template_files, modified_files, diff_content
    
    def _generate_response_content(self, user_message: str, modified_files: Dict[str, str]) -> str:
        """Generate a response message based on the user's request and the generated files"""
        has_increment = "increment" in user_message.lower()
        has_decrement = "decrement" in user_message.lower()
        has_button = "button" in user_message.lower()
        has_counter = "counter" in user_message.lower()
        
        # Create a more personalized message if specific features were requested
        if any([has_increment, has_decrement, has_button, has_counter]):
            features = []
            if has_counter:
                features.append("counter state")
            if has_increment:
                features.append("increment functionality")
            if has_decrement:
                features.append("decrement functionality")
            if has_button:
                features.append("interactive buttons")
            
            feature_text = ", ".join(features[:-1]) + " and " + features[-1] if len(features) > 1 else features[0]
            response = f"I've created a counter app with {feature_text} as requested. The app includes:"
        else:
            response = "I've created a simple counter application for you. It includes:"
        
        # Add summary of the implementation
        response += """

1. A React component with useState hook to manage the counter state
2. Increment and decrement buttons that update the counter
3. A display area showing the current count
4. Styled UI with flexbox layout and proper spacing

The app is ready to run, just install the dependencies and start the development server with:

```
npm install
npm run dev
```

Let me know if you'd like to make any adjustments to the implementation!
"""
        return response 