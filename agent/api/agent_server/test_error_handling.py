import pytest
from fastapi.testclient import TestClient
from api.agent_server.async_server import app
from api.agent_server.models import AgentMessage, MessageKind


def test_validation_exception_handler():
    """Test that the validation exception handler provides user-friendly error messages for enum validation errors."""
    client = TestClient(app)
    
    response = client.post(
        "/message",
        json={
            "allMessages": [
                {
                    "role": "user",
                    "content": "Hello"
                },
                {
                    "role": "assistant",
                    "kind": "INVALID_VALUE",  # Invalid enum value
                    "content": "Test content"
                }
            ],
            "applicationId": "test-app",
            "traceId": "test-trace"
        }
    )
    
    assert response.status_code == 422
    error_detail = response.json()["detail"]
    
    # Find the error related to MessageKind
    message_kind_error = None
    for error in error_detail:
        if "MessageKind" in str(error.get("loc", [])) or "kind" in str(error.get("loc", [])):
            message_kind_error = error
            break
    
    assert message_kind_error is not None
    assert "INVALID_VALUE" in message_kind_error["msg"]
    assert "Expected one of" in message_kind_error["msg"]
    
    response = client.post(
        "/message",
        json={
            "allMessages": [
                {
                    "role": "user",
                    "content": "Hello"
                },
                {
                    "role": "assistant",
                    "kind": "stageresult",  # Wrong case
                    "content": "Test content"
                }
            ],
            "applicationId": "test-app",
            "traceId": "test-trace"
        }
    )
    
    assert response.status_code == 422
    error_detail = response.json()["detail"]
    
    # Find the error related to MessageKind
    message_kind_error = None
    for error in error_detail:
        if "MessageKind" in str(error.get("loc", [])) or "kind" in str(error.get("loc", [])):
            message_kind_error = error
            break
    
    assert message_kind_error is not None
    assert "casing" in message_kind_error["msg"].lower() or "case" in message_kind_error["msg"].lower()
