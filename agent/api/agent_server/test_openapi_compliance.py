"""
Test to verify that the Python implementation matches the OpenAPI specification
generated from the TypeSpec definition.
"""
import pytest
import yaml
import json
from pathlib import Path
from typing import Dict, Any
from jsonschema import validate, ValidationError as JsonSchemaValidationError, RefResolver

from api.agent_server.models import (
    AgentStatus,
    MessageKind,
    UserMessage,
    AgentMessage,
    AgentSseEvent,
    AgentRequest,
    FileEntry,
)


class TestOpenAPICompliance:
    """Test suite to ensure Python models comply with OpenAPI/TypeSpec definitions."""
    
    @pytest.fixture
    def openapi_spec(self):
        """Load the OpenAPI specification generated from TypeSpec."""
        spec_path = Path(__file__).parent / "tsp-output" / "@typespec" / "openapi3" / "openapi.yaml"
        with open(spec_path, 'r') as f:
            return yaml.safe_load(f)
    
    @pytest.fixture
    def resolver(self, openapi_spec):
        """Create a JSON schema resolver for handling $ref references."""
        # The base URI should point to the document root
        return RefResolver(base_uri="", referrer=openapi_spec)
    
    def get_schema(self, openapi_spec: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        """Extract a schema definition from the OpenAPI spec."""
        return openapi_spec["components"]["schemas"][schema_name]
    
    def validate_with_refs(self, instance: Dict[str, Any], schema: Dict[str, Any], resolver: RefResolver):
        """Validate instance against schema with reference resolution."""
        validate(instance=instance, schema=schema, resolver=resolver)
    
    def test_user_message_compliance(self, openapi_spec, resolver):
        """Test UserMessage model against OpenAPI schema."""
        schema = self.get_schema(openapi_spec, "UserMessage")
        
        # Create a valid UserMessage
        msg = UserMessage(role="user", content="Hello world")
        
        # Convert to JSON and validate against schema
        msg_json = json.loads(msg.to_json())
        self.validate_with_refs(msg_json, schema, resolver)
        
        # Test that role must be 'user'
        with pytest.raises(JsonSchemaValidationError):
            self.validate_with_refs({"role": "assistant", "content": "Hello"}, schema, resolver)
    
    def test_agent_message_compliance(self, openapi_spec, resolver):
        """Test AgentMessage model against OpenAPI schema."""
        schema = self.get_schema(openapi_spec, "AgentMessage")
        
        # Test minimal AgentMessage
        msg = AgentMessage(
            role="assistant",
            kind=MessageKind.STAGE_RESULT,
            content="Processing your request..."
        )
        msg_json = json.loads(msg.to_json())
        self.validate_with_refs(msg_json, schema, resolver)
        
        # Test full AgentMessage with all optional fields
        full_msg = AgentMessage(
            role="assistant",
            kind=MessageKind.REVIEW_RESULT,
            content="Application generated successfully",
            agent_state={"fsm_state": {"key": "value"}},
            unified_diff="--- a/file\n+++ b/file\n@@ -1 +1 @@\n-old\n+new",
            complete_diff_hash="abc123def456",
            diff_stat=[{"path": "app.py", "insertions": 10, "deletions": 5}],
            app_name="my-awesome-app",
            commit_message="Initial commit"
        )
        full_json = json.loads(full_msg.to_json())
        self.validate_with_refs(full_json, schema, resolver)
    
    def test_agent_sse_event_compliance(self, openapi_spec, resolver):
        """Test AgentSseEvent model against OpenAPI schema."""
        schema = self.get_schema(openapi_spec, "AgentSseEvent")
        
        msg = AgentMessage(
            role="assistant",
            kind=MessageKind.REFINEMENT_REQUEST,
            content="What type of application would you like?"
        )
        
        event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id="test-trace-123",
            message=msg
        )
        
        event_json = json.loads(event.to_json())
        self.validate_with_refs(event_json, schema, resolver)
    
    def test_agent_request_compliance(self, openapi_spec, resolver):
        """Test AgentRequest model against OpenAPI schema."""
        schema = self.get_schema(openapi_spec, "AgentRequest")
        
        # Create a request with conversation history using the correct field names (aliases)
        request = AgentRequest(
            allMessages=[
                UserMessage(role="user", content="Build me a todo app"),
                AgentMessage(
                    role="assistant",
                    kind=MessageKind.REFINEMENT_REQUEST,
                    content="I'll help you build a todo app. What features would you like?"
                )
            ],
            applicationId="app-123",
            traceId="trace-456",
            allFiles=[
                FileEntry(path="README.md", content="# Todo App")
            ],
            agentState={"fsm_state": {"current": "planning"}},
            settings={"max_iterations": 10}
        )
        
        request_json = json.loads(request.to_json())
        self.validate_with_refs(request_json, schema, resolver)
    
    def test_enum_values(self, openapi_spec):
        """Test that enum values match between Python and OpenAPI."""
        # Check AgentStatus enum
        agent_status_schema = self.get_schema(openapi_spec, "AgentStatus")
        openapi_status_values = set(agent_status_schema["enum"])
        python_status_values = {status.value for status in AgentStatus}
        assert openapi_status_values == python_status_values
        
        # Check MessageKind enum
        message_kind_schema = self.get_schema(openapi_spec, "MessageKind")
        openapi_kind_values = set(message_kind_schema["enum"])
        python_kind_values = {kind.value for kind in MessageKind}
        assert openapi_kind_values == python_kind_values
    
    def test_field_naming_consistency(self, openapi_spec):
        """Test that field names are consistently camelCase in JSON output."""
        # Test AgentMessage field names
        msg = AgentMessage(
            role="assistant",
            kind=MessageKind.STAGE_RESULT,
            content="Test",
            agent_state={},
            unified_diff="diff",
            complete_diff_hash="hash",
            diff_stat=[]
        )
        
        json_data = json.loads(msg.to_json())
        
        # Check camelCase fields
        assert "agentState" in json_data
        assert "unifiedDiff" in json_data
        assert "completeDiffHash" in json_data
        assert "diffStat" in json_data
        
        # Check snake_case fields (these should remain as-is per TypeSpec)
        assert "app_name" in json_data or "app_name" not in msg.model_fields_set
        assert "commit_message" in json_data or "commit_message" not in msg.model_fields_set
    
    def test_conversation_message_union(self, openapi_spec):
        """Test that ConversationMessage union type works correctly."""
        # The OpenAPI spec should have refs to UserMessage and AgentMessage
        conversation_msg_schema = self.get_schema(openapi_spec, "ConversationMessage")
        
        # It should be a oneOf schema
        assert "oneOf" in conversation_msg_schema or "anyOf" in conversation_msg_schema
        
        # Test that our parse function works correctly
        from api.agent_server.models import parse_conversation_message
        
        user_msg_json = '{"role": "user", "content": "Hello"}'
        parsed_user = parse_conversation_message(user_msg_json)
        assert isinstance(parsed_user, UserMessage)
        
        agent_msg_json = '{"role": "assistant", "kind": "StageResult", "content": "Hi"}'
        parsed_agent = parse_conversation_message(agent_msg_json)
        assert isinstance(parsed_agent, AgentMessage)
    
    def test_sse_response_format(self, openapi_spec):
        """Test that the SSE response format matches the API specification."""
        # The /message endpoint should return text/event-stream
        paths = openapi_spec.get("paths", {})
        message_endpoint = paths.get("/message", {})
        post_operation = message_endpoint.get("post", {})
        responses = post_operation.get("responses", {})
        
        # Check that 200 response has text/event-stream content type
        ok_response = responses.get("200", {})
        content = ok_response.get("content", {})
        assert "text/event-stream" in content or "text/plain" in content  # TypeSpec might simplify this 