"""
Test to verify that the Python models match the TypeSpec API definition.
This ensures that the implementation stays in sync with the API specification.
"""
import pytest
import json

from api.agent_server.models import (
    AgentStatus,
    MessageKind,
    UserMessage,
    AgentMessage,
    AgentSseEvent,
    AgentRequest,
    FileEntry,
    DiffStatEntry,
    parse_conversation_message
)


class TestTspCompliance:
    """Test suite to ensure Python models comply with TypeSpec definitions."""

    def test_agent_status_enum(self):
        """Verify AgentStatus enum values match TypeSpec."""
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.IDLE.value == "idle"
        
    def test_message_kind_enum(self):
        """Verify MessageKind enum values match TypeSpec."""
        assert MessageKind.STAGE_RESULT.value == "StageResult"
        assert MessageKind.RUNTIME_ERROR.value == "RuntimeError"
        assert MessageKind.REFINEMENT_REQUEST.value == "RefinementRequest"
        assert MessageKind.REVIEW_RESULT.value == "ReviewResult"
        assert MessageKind.KEEP_ALIVE.value == "KeepAlive"

    def test_user_message_structure(self):
        """Verify UserMessage structure matches TypeSpec."""
        # Test valid user message
        msg = UserMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        
        # Test JSON serialization with correct field names
        json_str = msg.to_json()
        data = json.loads(json_str)
        assert data["role"] == "user"
        assert data["content"] == "Hello"
        
        # Test deserialization
        msg2 = UserMessage.from_json(json_str)
        assert msg2 == msg

    def test_diff_stat_entry_structure(self):
        """Verify DiffStatEntry structure matches TypeSpec."""
        entry = DiffStatEntry(path="src/app.py", insertions=10, deletions=5)
        assert entry.path == "src/app.py"
        assert entry.insertions == 10
        assert entry.deletions == 5

    def test_agent_message_structure(self):
        """Verify AgentMessage structure matches TypeSpec."""
        # Test minimal agent message
        msg = AgentMessage(
            role="assistant",
            kind=MessageKind.STAGE_RESULT,
            content="Processing..."
        )
        assert msg.role == "assistant"
        assert msg.kind == MessageKind.STAGE_RESULT
        assert msg.content == "Processing..."
        
        # Test full agent message with all optional fields
        diff_stats = [DiffStatEntry(path="app.py", insertions=20, deletions=0)]
        full_msg = AgentMessage(
            role="assistant",
            kind=MessageKind.REVIEW_RESULT,
            content="Complete",
            agent_state={"fsm_state": {"some": "data"}},
            unified_diff="--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new",
            complete_diff_hash="abc123",
            diff_stat=diff_stats,
            app_name="my-cool-app",
            commit_message="Initial commit"
        )
        
        # Test JSON serialization uses camelCase
        json_str = full_msg.to_json()
        data = json.loads(json_str)
        assert "agentState" in data
        assert "unifiedDiff" in data
        assert "completeDiffHash" in data
        assert "diffStat" in data
        assert data["app_name"] == "my-cool-app"
        assert data["commit_message"] == "Initial commit"

    def test_agent_sse_event_structure(self):
        """Verify AgentSseEvent structure matches TypeSpec."""
        msg = AgentMessage(
            role="assistant",
            kind=MessageKind.STAGE_RESULT,
            content="Hello"
        )
        event = AgentSseEvent(
            status=AgentStatus.RUNNING,
            traceId="trace123",
            message=msg
        )
        
        # Test JSON serialization
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["status"] == "running"
        assert data["traceId"] == "trace123"
        assert data["message"]["content"] == "Hello"

    def test_file_entry_structure(self):
        """Verify FileEntry structure matches TypeSpec."""
        file_entry = FileEntry(path="src/main.py", content="print('hello')")
        assert file_entry.path == "src/main.py"
        assert file_entry.content == "print('hello')"

    def test_agent_request_structure(self):
        """Verify AgentRequest structure matches TypeSpec."""
        # Create conversation messages
        user_msg = UserMessage(role="user", content="Build an app")
        agent_msg = AgentMessage(
            role="assistant",
            kind=MessageKind.REFINEMENT_REQUEST,
            content="What kind of app?"
        )
        
        # Create file entries
        files = [FileEntry(path="README.md", content="# My App")]
        
        # Create request using camelCase aliases
        request = AgentRequest(
            allMessages=[user_msg, agent_msg],
            applicationId="app123",
            traceId="trace456",
            allFiles=files,
            agentState={"some": "state"},
            settings={"max_iterations": 5}
        )
        
        # Test JSON serialization
        json_str = request.to_json()
        data = json.loads(json_str)
        assert data["allMessages"][0]["role"] == "user"
        assert data["applicationId"] == "app123"
        assert data["traceId"] == "trace456"
        assert data["allFiles"][0]["path"] == "README.md"
        assert data["agentState"]["some"] == "state"
        assert data["settings"]["max_iterations"] == 5

    def test_conversation_message_parsing(self):
        """Test parsing of conversation messages."""
        # Test parsing user message
        user_json = '{"role": "user", "content": "Hello"}'
        msg = parse_conversation_message(user_json)
        assert isinstance(msg, UserMessage)
        assert msg.content == "Hello"
        
        # Test parsing agent message
        agent_json = '{"role": "assistant", "kind": "StageResult", "content": "Hi"}'
        msg = parse_conversation_message(agent_json)
        assert isinstance(msg, AgentMessage)
        assert msg.content == "Hi"
        assert msg.kind == MessageKind.STAGE_RESULT
        
        # Test invalid role
        with pytest.raises(ValueError, match="Unknown role"):
            parse_conversation_message('{"role": "system", "content": "Error"}')


def test_tsp_field_aliases():
    """Verify that all camelCase aliases are properly configured."""
    # AgentMessage aliases
    msg = AgentMessage(
        role="assistant",
        kind=MessageKind.STAGE_RESULT,
        content="Test",
        agentState={"test": "data"},
        unifiedDiff="diff",
        completeDiffHash="hash",
        diffStat=[]
    )
    json_data = json.loads(msg.to_json())
    assert "agentState" in json_data
    assert "unifiedDiff" in json_data
    assert "completeDiffHash" in json_data
    assert "diffStat" in json_data
    
    # AgentSseEvent aliases
    event = AgentSseEvent(
        status=AgentStatus.IDLE,
        traceId="123",
        message=msg
    )
    json_data = json.loads(event.to_json())
    assert "traceId" in json_data
    
    # AgentRequest aliases
    req = AgentRequest(
        allMessages=[],
        applicationId="app",
        traceId="trace",
        allFiles=[],
        agentState={}
    )
    json_data = json.loads(req.to_json())
    assert "allMessages" in json_data
    assert "applicationId" in json_data
    assert "traceId" in json_data
    assert "allFiles" in json_data
    assert "agentState" in json_data 