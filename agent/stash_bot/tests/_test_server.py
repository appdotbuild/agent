import uuid
import pytest
import time
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import BackgroundTasks

from server import app, BuildRequest

# generate token random for single test run
_token = str(uuid.uuid4())

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_uuid():
    with patch("uuid.uuid4") as mock:
        mock.return_value.hex = "test-trace-id"
        yield mock


# simplified mock for generate_bot that does nothing but wait a tiny bit and return
@pytest.fixture
def mock_generate_bot():
    def mock_implementation(write_url, read_url, prompts, trace_id, bot_id, capabilities=None):
        # just wait a tiny bit to simulate some work
        time.sleep(0.1)
        return None
    
    with patch("server.generate_bot", side_effect=mock_implementation) as mock:
        yield mock


@pytest.fixture
def mock_env_token():
    with patch.dict("os.environ", {"BUILDER_TOKEN": _token}):
        yield


# fixture to provide auth headers for all tests
@pytest.fixture
def auth_headers():
    with patch.dict("os.environ", {"BUILDER_TOKEN": _token}):
        yield {"Authorization": f"Bearer {_token}"}


def test_healthcheck(client, auth_headers):
    # test the healthcheck endpoint
    response = client.get("/healthcheck", headers=auth_headers)
    
    # verify response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "ok"
    assert data["trace_id"] is None
    assert data["metadata"] == {}


def test_compile_endpoint(client, mock_uuid, mock_generate_bot, auth_headers):
    # prepare test data
    request_data = {
        "writeUrl": "https://example.com/write",
        "prompt": "test prompt",
        "botId": "test-bot-id"
    }
    
    # call the endpoint
    response = client.post("/compile", json=request_data, headers=auth_headers)
    
    # verify response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "done"
    assert data["trace_id"] == "test-trace-id"
    
    # verify that generate_bot was called with correct parameters
    mock_generate_bot.assert_called_once_with(
        request_data["writeUrl"],
        None,  # read_url is None
        [request_data["prompt"]],  # prompt is wrapped in a list
        "test-trace-id",
        request_data["botId"],
        None
    )


def test_compile_endpoint_without_bot_id(client, mock_uuid, mock_generate_bot, auth_headers):
    # prepare test data without botId
    request_data = {
        "writeUrl": "https://example.com/write",
        "prompt": "test prompt"
    }
    
    # call the endpoint
    response = client.post("/compile", json=request_data, headers=auth_headers)
    
    # verify response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "done"
    assert data["trace_id"] == "test-trace-id"
    
    # verify that generate_bot was called with correct parameters
    mock_generate_bot.assert_called_once_with(
        request_data["writeUrl"],
        None,  # read_url is None
        [request_data["prompt"]],  # prompt is wrapped in a list
        "test-trace-id",
        None,
        None
    )


def test_compile_endpoint_with_read_url(client, auth_headers, mock_generate_bot, mock_uuid):
    # prepare test data with readUrl
    request_data = {
        "readUrl": "https://example.com/read",
        "writeUrl": "https://example.com/write",
        "prompt": "test prompt"
    }
    
    # call the endpoint
    response = client.post("/compile", json=request_data, headers=auth_headers)
    
    # verify response - readUrl is acceptable in current implementation
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "done"
    
    # verify generate_bot was called with the readUrl
    mock_generate_bot.assert_called_once_with(
        request_data["writeUrl"],
        request_data["readUrl"],
        [request_data["prompt"]],
        "test-trace-id",
        None,
        None
    )


def test_unauthorized_access(client, mock_generate_bot, mock_uuid):
    # test without authorization header
    response = client.get("/healthcheck", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    
    response = client.post("/compile", json={"writeUrl": "url", "prompt": "test"}, 
                          headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    
    # verify generate_bot was not called since auth should fail first
    mock_generate_bot.assert_not_called()


def test_authorized_access(client, mock_env_token, mock_uuid, mock_generate_bot, auth_headers):
    # test with correct authorization header
    response = client.get("/healthcheck", headers=auth_headers)
    assert response.status_code == 200
    
    # prepare test data for compile endpoint
    request_data = {
        "writeUrl": "https://example.com/write",
        "prompt": "test prompt"
    }
    
    # call the compile endpoint with proper mocking
    response = client.post(
        "/compile", 
        json=request_data, 
        headers=auth_headers
    )
    
    # verify response
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["message"] == "done"
    
    # verify that generate_bot was called
    mock_generate_bot.assert_called_once()


def test_generate_bot_mock(auth_headers, mock_env_token):
    # test that our mock works correctly
    mock_fn = MagicMock()
    
    # patch the generate_bot function
    with patch("server.generate_bot", mock_fn):
        # call the function through the app's routes
        client = TestClient(app)
        with patch("uuid.uuid4") as mock_uuid:
            mock_uuid.return_value.hex = "test-trace-id"
            
            # make the request
            response = client.post(
                "/compile",
                json={"writeUrl": "test-url", "prompt": "test-prompt"},
                headers=auth_headers
            )
            
            # verify the response
            assert response.status_code == 200
            
            # verify the mock was called with the correct arguments
            mock_fn.assert_called_once_with(
                "test-url", None, ["test-prompt"], "test-trace-id", None, None
            )


def test_background_task_addition(auth_headers, mock_env_token):
    # mock the background tasks
    mock_background_tasks = MagicMock(spec=BackgroundTasks)
    
    # create a request
    request = BuildRequest(
        writeUrl="https://example.com/write",
        prompt="test prompt",
        botId="test-bot-id"
    )
    
    # mock uuid and the compile function
    with patch("uuid.uuid4") as mock_uuid, \
         patch("server.generate_bot") as mock_generate_bot:
        
        mock_uuid.return_value.hex = "test-trace-id"
        
        # call the endpoint through the client
        client = TestClient(app)
        
        response = client.post(
            "/compile",
            json={
                "writeUrl": request.writeUrl,
                "prompt": request.prompt,
                "botId": request.botId
            },
            headers=auth_headers
        )
        
        # verify the response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["message"] == "done"
        assert data["trace_id"] == "test-trace-id" 
        