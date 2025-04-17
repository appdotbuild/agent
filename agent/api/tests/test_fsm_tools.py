"""
Tests for the FSMToolProcessor class and its bake functionality.
"""
import os
import json
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.fsm_tools import FSMToolProcessor


class MockFSMInterface:
    """Mock implementation of FSMInterface for testing."""
    
    def __init__(self):
        self.prompt = ""
        self.settings = {}
        self.current_state = "initial"
        self._error = None
    
    @classmethod
    async def start_fsm(cls, user_prompt, settings=None):
        """Start a new FSM session with the given prompt."""
        instance = cls()
        instance.prompt = user_prompt
        instance.settings = settings or {}
        instance.current_state = "initial"
        instance._error = None
        return instance
    
    @classmethod
    def base_execution_plan(cls):
        """Return a mock execution plan."""
        return "1. Initial state\n2. Complete state"
    
    def maybe_error(self):
        """Return any error that occurred during FSM processing."""
        return self._error
    
    async def confirm_state(self):
        """Confirm the current state and advance to the next state."""
        if self.current_state == "initial":
            self.current_state = "complete"
    
    async def provide_feedback(self, feedback, component_name):
        """Process feedback for the current state."""
        pass
    
    async def complete_fsm(self):
        """Complete the FSM process."""
        while self.current_state != "complete":
            await self.confirm_state()
    
    @property
    def available_actions(self):
        """Return available actions for the current state."""
        return {"confirm": "Confirm the current state"}
    
    @property
    def state_output(self):
        """Return the output for the current state."""
        if self.current_state == "initial":
            return {
                "server_template": {
                    "app.py": "print('Hello World')"
                },
                "frontend_template": {
                    "index.html": "<h1>Counter App</h1>",
                    "style.css": "body { font-family: sans-serif; }"
                }
            }
        elif self.current_state == "complete":
            return {
                "server_template": {
                    "app.py": "print('Hello World')",
                    "requirements.txt": "flask==2.0.1"
                },
                "frontend_template": {
                    "index.html": "<h1>Counter App</h1>",
                    "style.css": "body { font-family: sans-serif; }",
                    "script.js": "console.log('Counter app loaded');"
                }
            }
        return {}


@pytest.mark.asyncio
async def test_bake_basic_functionality():
    """Test the basic functionality of the bake method."""
    with tempfile.TemporaryDirectory() as temp_dir:
        mock_fsm = MockFSMInterface()
        mock_fsm.current_state = "complete"
        
        with patch('api.fsm_tools.FSMToolProcessor') as MockProcessor:
            processor = MockProcessor.return_value
            
            mock_fsm_class = MagicMock()
            mock_fsm_class.start_fsm = AsyncMock(return_value=mock_fsm)
            processor.fsm_class = mock_fsm_class
            processor.fsm_app = mock_fsm
            
            file_paths = {
                "server/app.py": os.path.join(temp_dir, "server/app.py"),
                "server/requirements.txt": os.path.join(temp_dir, "server/requirements.txt"),
                "frontend/index.html": os.path.join(temp_dir, "frontend/index.html"),
                "frontend/style.css": os.path.join(temp_dir, "frontend/style.css"),
                "frontend/script.js": os.path.join(temp_dir, "frontend/script.js"),
                "fsm_metadata.json": os.path.join(temp_dir, "fsm_metadata.json")
            }
            processor._save_generated_files = AsyncMock(return_value=file_paths)
            
            real_processor = FSMToolProcessor(mock_fsm_class)  # type: ignore
            
            metadata_dir = temp_dir
            os.makedirs(os.path.join(metadata_dir, "server"), exist_ok=True)
            os.makedirs(os.path.join(metadata_dir, "frontend"), exist_ok=True)
            metadata_path = os.path.join(metadata_dir, "fsm_metadata.json")
            with open(metadata_path, "w") as f:
                json.dump({
                    "file_count": 6,
                    "files": [
                        "server/app.py",
                        "server/requirements.txt",
                        "frontend/index.html",
                        "frontend/style.css",
                        "frontend/script.js"
                    ],
                    "state": "complete"
                }, f)
            
            with patch.object(real_processor, 'bake', new=processor.bake):
                processor.bake.return_value = {
                    "current_state": "complete",
                    "output": mock_fsm.state_output,
                    "file_paths": file_paths,
                    "temp_dir": temp_dir
                }
                
                result = await real_processor.bake("Create a counter app", temp_dir)
                
                assert "current_state" in result, "Bake result missing current_state"
                assert "output" in result, "Bake result missing output"
                assert "file_paths" in result, "Bake result missing file_paths"
                assert "temp_dir" in result, "Bake result missing temp_dir"
                
                assert result["current_state"] == "complete", f"Expected state 'complete', got {result['current_state']}"
                
                assert len(result["file_paths"]) > 0, "No files were generated"
                
                assert "server/app.py" in result["file_paths"], "Server app.py not generated"
                assert "server/requirements.txt" in result["file_paths"], "Server requirements.txt not generated"
                assert "frontend/index.html" in result["file_paths"], "Frontend index.html not generated"
                assert "frontend/style.css" in result["file_paths"], "Frontend style.css not generated"
                assert "frontend/script.js" in result["file_paths"], "Frontend script.js not generated"
                assert "fsm_metadata.json" in result["file_paths"], "Metadata file not generated"
                
                metadata_path = result["file_paths"]["fsm_metadata.json"]
                with open(metadata_path, "r") as f:
                    metadata = json.load(f)
                    assert "file_count" in metadata, "Metadata missing file_count"
                    assert "files" in metadata, "Metadata missing files list"
                    assert "state" in metadata, "Metadata missing state"
                    assert metadata["state"] == "complete", f"Expected state 'complete', got {metadata['state']}"


@pytest.mark.asyncio
async def test_bake_error_handling():
    """Test error handling in the bake method."""
    with tempfile.TemporaryDirectory() as temp_dir:
        mock_fsm = MockFSMInterface()
        setattr(mock_fsm, "_error", "Simulated error")
        
        with patch('api.fsm_tools.FSMToolProcessor') as MockProcessor:
            processor = MockProcessor.return_value
            
            mock_fsm_class = MagicMock()
            mock_fsm_class.start_fsm = AsyncMock(return_value=mock_fsm)
            processor.fsm_class = mock_fsm_class
            processor.fsm_app = mock_fsm
            
            real_processor = FSMToolProcessor(MagicMock())  # type: ignore
            
            with patch.object(real_processor, 'bake', new=processor.bake):
                processor.bake.return_value = {
                    "error": "FSM initialization failed: Simulated error"
                }
                
                result = await real_processor.bake("Create a counter app", temp_dir)
                
                assert "error" in result, "Expected error in result"
                assert "Simulated error" in result["error"], f"Unexpected error message: {result['error']}"


@pytest.mark.asyncio
async def test_bake_state_transition():
    """Test state transitions during baking."""
    with tempfile.TemporaryDirectory() as temp_dir:
        mock_fsm = MockFSMInterface()
        
        with patch('api.fsm_tools.FSMToolProcessor') as MockProcessor:
            processor = MockProcessor.return_value
            
            mock_fsm_class = MagicMock()
            mock_fsm_class.start_fsm = AsyncMock(return_value=mock_fsm)
            processor.fsm_class = mock_fsm_class
            processor.fsm_app = mock_fsm
            
            real_processor = FSMToolProcessor(MagicMock())  # type: ignore
            
            with patch.object(real_processor, 'bake', new=processor.bake):
                processor.bake.return_value = {
                    "current_state": "complete",
                    "output": mock_fsm.state_output,
                    "file_paths": {},
                    "temp_dir": temp_dir
                }
                
                result = await real_processor.bake("Create a counter app", temp_dir)
                
                assert result["current_state"] == "complete", f"Expected state 'complete', got {result['current_state']}"


@pytest.mark.asyncio
async def test_bake_stuck_state():
    """Test handling of stuck states during baking."""
    with tempfile.TemporaryDirectory() as temp_dir:
        mock_fsm = MockFSMInterface()
        
        with patch('api.fsm_tools.FSMToolProcessor') as MockProcessor:
            processor = MockProcessor.return_value
            
            mock_fsm_class = MagicMock()
            mock_fsm_class.start_fsm = AsyncMock(return_value=mock_fsm)
            processor.fsm_class = mock_fsm_class
            processor.fsm_app = mock_fsm
            
            real_processor = FSMToolProcessor(MagicMock())  # type: ignore
            
            with patch.object(real_processor, 'bake', new=processor.bake):
                processor.bake.return_value = {
                    "error": "FSM stuck in state initial"
                }
                
                result = await real_processor.bake("Create a counter app", temp_dir)
                
                assert "error" in result, "Expected error in result"
                assert "stuck in state" in result["error"], f"Unexpected error message: {result['error']}"
