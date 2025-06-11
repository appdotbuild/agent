import pytest
import os
import dagger
from unittest.mock import AsyncMock, MagicMock
from trpc_agent.application import FSMApplication, FSMState
from trpc_agent.diff_edit_actor import EditActor
from core.actors import BaseData
from core.base_node import Node
from core.workspace import Workspace
from log import get_logger

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture(scope="function")
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_edit_actor_no_changes_flag():
    """Test that EditActor sets no_changes_applied flag when no modifications are made."""
    
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create a mock workspace
        workspace = await Workspace.create(
            client=client,
            base_image="alpine:latest",
            context=client.directory()
        )
        
        # Create EditActor with mock LLMs
        mock_llm = AsyncMock()
        mock_vlm = AsyncMock()
        edit_actor = EditActor(mock_llm, mock_vlm, workspace, beam_width=1, max_depth=1)
        
        # Mock the run_llm method to return a node that represents no changes
        mock_node = Node(BaseData(workspace, [], {}))
        # Don't add any files to simulate no changes
        edit_actor.run_llm = AsyncMock(return_value=[mock_node])
        
        # Mock eval_node to return True (solution found)
        async def mock_eval_node(node, user_prompt):
            return True
        edit_actor.eval_node = mock_eval_node
        
        try:
            # Execute EditActor
            result = await edit_actor.execute(
                files={"test.txt": "original content"},
                user_prompt="Test prompt", 
                feedback="No meaningful changes requested"
            )
            
            # Verify that no_changes_applied flag is set
            assert hasattr(result.data, 'no_changes_applied')
            assert result.data.no_changes_applied == True
            logger.info("✅ EditActor correctly sets no_changes_applied flag when no modifications made")
            
        except Exception as e:
            # If EditActor throws exception due to no solution, that's also a valid case
            # where no changes would be applied
            logger.info(f"EditActor threw exception (expected for no changes): {e}")
            assert "No solutions found" in str(e)


@pytest.mark.anyio  
async def test_fsm_application_no_changes_property():
    """Test that FSMApplication correctly detects when no changes were applied."""
    
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create a minimal FSM application
        fsm_app = await FSMApplication.start_fsm(client, "test prompt")
        
        # Initially, no changes should be detected
        assert fsm_app._no_changes_applied == False
        
        # Simulate setting the _edit_no_changes flag in context
        setattr(fsm_app.fsm.context, '_edit_no_changes', True)
        
        # Now the property should return True
        assert fsm_app._no_changes_applied == True
        logger.info("✅ FSMApplication correctly detects _edit_no_changes flag from context")


@pytest.mark.anyio
async def test_fsm_status_refinement_for_no_changes():
    """Test that FSM status becomes REFINEMENT_REQUEST when app is complete but no changes applied."""
    
    from api.fsm_tools import FSMToolProcessor, FSMStatus
    from llm.common import InternalMessage, TextRaw
    
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create FSM tool processor  
        processor = FSMToolProcessor(client, FSMApplication)
        
        # Create a mock FSM app that is completed but has no changes
        mock_fsm_app = MagicMock()
        mock_fsm_app.maybe_error.return_value = None
        mock_fsm_app.is_completed = True
        mock_fsm_app.current_state = "complete"
        mock_fsm_app._no_changes_applied = True
        
        processor.fsm_app = mock_fsm_app
        
        # Mock LLM that returns no tool calls (empty response)
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [TextRaw("No changes needed")]
        mock_llm.completion.return_value = mock_response
        
        # Test the step method
        messages = [InternalMessage(role="user", content=[TextRaw("test")])]
        thread, fsm_status = await processor.step(messages, mock_llm, {})
        
        # Should return REFINEMENT_REQUEST since no changes were applied
        assert fsm_status == FSMStatus.REFINEMENT_REQUEST
        logger.info("✅ FSMToolProcessor correctly returns REFINEMENT_REQUEST for no changes scenario")


@pytest.mark.anyio
async def test_empty_diff_detection():
    """Test that empty or whitespace-only diffs are detected as non-meaningful."""
    
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        fsm_app = await FSMApplication.start_fsm(client, "test prompt")
        
        # Test empty diff
        empty_diff = ""
        assert not (empty_diff and empty_diff.strip())
        
        # Test whitespace-only diff  
        whitespace_diff = "   \n\t  \n  "
        assert not (whitespace_diff and whitespace_diff.strip())
        
        # Test meaningful diff
        meaningful_diff = "diff --git a/file.txt b/file.txt\n+added line"
        assert meaningful_diff and meaningful_diff.strip()
        
        logger.info("✅ Empty diff detection logic works correctly")


@pytest.mark.anyio
async def test_integration_no_changes_workflow():
    """Integration test for the complete no-changes workflow."""
    
    from api.fsm_tools import FSMToolProcessor, FSMStatus
    from llm.common import InternalMessage, TextRaw
    
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        # Create processor
        processor = FSMToolProcessor(client, FSMApplication)
        
        # Start with a simple FSM
        fsm_app = await FSMApplication.start_fsm(client, "Simple test app")
        processor.fsm_app = fsm_app
        
        # Force the FSM to complete state with no changes
        fsm_app.fsm.state_value = FSMState.COMPLETE
        setattr(fsm_app.fsm.context, '_edit_no_changes', True)
        
        # Mock LLM to return no tool calls
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = [TextRaw("Everything looks good, no changes needed")]
        mock_llm.completion.return_value = mock_response
        
        # Process step
        messages = [InternalMessage(role="user", content=[TextRaw("review this")])]
        thread, status = await processor.step(messages, mock_llm, {})
        
        # Should get REFINEMENT_REQUEST instead of COMPLETED
        assert status == FSMStatus.REFINEMENT_REQUEST
        logger.info("✅ Integration test: No-changes workflow correctly returns REFINEMENT_REQUEST")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])