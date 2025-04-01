# Agent Server API

This API provides a REST+SSE (Server-Sent Events) endpoint for communication between the Platform (Backend) and the Agent Server.

## Overview

The Agent Server API is designed to be stateless, maintaining only transient in-memory state during processing. It provides a single `/message` endpoint that accepts a POST request and responds with a stream of Server-Sent Events (SSE).

## API Endpoints

### POST /message

Sends user input and conversation context to the Agent Server and receives a stream of SSE events.

#### Request Body

```json
{
  "allMessages": ["Build me an app to plan my meals"],
  "chatbotId": "jhagsjdas",
  "traceId": "asdsaslsa",
  "agentState": null,
  "settings": {"max-iterations": 3}
}
```

| Field | Type | Description |
|-------|------|-------------|
| `allMessages` | string[] | History of all user messages in the conversation thread |
| `chatbotId` | string | Unique identifier for the chatbot instance |
| `traceId` | string | Unique identifier for this request/response cycle |
| `agentState` | object \| null | The full state of the Agent Server to restore from (opaque object) |
| `settings` | object | Settings for the agent execution (e.g., max iterations) |

#### SSE Response

The server responds with a stream of Server-Sent Events (SSE). Each event contains a JSON payload in the following format:

```json
{
  "status": "running",
  "traceId": "asdsaslsa",
  "message": {
    "kind": "StageResult",
    "content": "I've generated the initial plan.",
    "agentState": { ... },
    "unifiedDiff": null
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | "running" or "idle" - defines if the Agent is active or waiting |
| `traceId` | string | Corresponding traceId from the input |
| `message.kind` | string | Type of message: "StageResult", "FeedbackResponse", or "RuntimeError" |
| `message.content` | string | Formatted content, can be long and include formatting |
| `message.agentState` | object \| null | Updated state of the Agent Server for the next request |
| `message.unifiedDiff` | string \| null | Unified diff format string showing changes (if any) |

## Message Kinds

- **StageResult**: Intermediate result while the agent is still running
- **FeedbackResponse**: Agent has stopped and is asking for feedback
- **RuntimeError**: Agent failed and results are likely non-retriable

## Usage Examples

### Starting a new conversation:

```bash
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "allMessages": ["Build me an app to plan my meals"],
    "chatbotId": "jhagsjdas",
    "traceId": "asdsaslsa",
    "agentState": null,
    "settings": {"max-iterations": 3}
  }'
```

### Continuing a conversation:

```bash
curl -X POST http://localhost:8000/message \
  -H "Content-Type: application/json" \
  -d '{
    "allMessages": ["Build me an app to plan my meals", "Yes, include dietary restrictions"],
    "chatbotId": "jhagsjdas",
    "traceId": "asdsaslsa2",
    "agentState": { ... },
    "settings": {"max-iterations": 3}
  }'
```

## Running the Server

```bash
python run.py --host 127.0.0.1 --port 8000
```

## Testing the API

Use the provided test client:

```bash
python test_client.py --url http://localhost:8000 --message "Build me an app to plan my meals"
```