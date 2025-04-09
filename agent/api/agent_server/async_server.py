import logging
import asyncio
from typing import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
    ErrorResponse
)
from .interface import AgentInterface
from .async_agent_session import AsyncAgentSession
from .empty_diff_impl import EmptyDiffAgentImplementation

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Async Agent Server API")
    yield
    logger.info("Shutting down Async Agent Server API")

app = FastAPI(
    title="Async Agent Server API",
    description="Async API for communication between the Platform (Backend) and the Agent Server",
    version="1.0.0",
    lifespan=lifespan
)


async def run_agent[T: AgentInterface](
    request: AgentRequest,
    agent_class: type[T],
    *args,
    **kwargs,
) -> AsyncGenerator[str, None]:
    logger.info(f"Creating new agent session for {request.chatbot_id}:{request.trace_id}")
    event_tx, event_rx = anyio.create_memory_object_stream[AgentSseEvent](max_buffer_size=0)
    agent = agent_class(
        chatbot_id=request.chatbot_id,
        trace_id=request.trace_id,
        settings=request.settings,
        *args,
        **kwargs
    )
    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(agent.process, request, event_tx)
            async with event_rx:
                async for event in event_rx:
                    yield f"data: {event.to_json()}\n\n"
    except* Exception as excgroup:
        for e in excgroup.exceptions:
            logger.error(f"Error in SSE generator: {str(e)}")
            error_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=request.trace_id,
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing request: {str(e)}",
                    agent_state=None,
                    unified_diff=""
                )
            )
            yield f"data: {error_event.to_json()}\n\n"
    finally:
        logger.info(f"Cleaning up agent session for {request.chatbot_id}:{request.trace_id}")


@app.post("/message", response_model=None)
async def message(request: AgentRequest) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.

    Platform (Backend) -> Agent Server API Spec:
    POST Request:
    - allMessages: [str] - history of all user messages
    - chatbotId: str - required for Agent Server for tracing
    - traceId: str - required - a string used in SSE events
    - agentState: {..} or null - the full state of the Agent to restore from
    - settings: {...} - json with settings with number of iterations etc

    SSE Response:
    - status: "running" | "idle" - defines if the Agent stopped or continues running
    - traceId: corresponding traceId of the input
    - message: {kind, content, agentState, unifiedDiff} - response from the Agent Server

    Args:
        request: The agent request containing all necessary fields

    Returns:
        Streaming response with SSE events according to the API spec
    """
    try:
        logger.info(f"Received message request for chatbot {request.chatbot_id}, trace {request.trace_id}")

        # Start the SSE stream
        logger.info(f"Starting SSE stream for chatbot {request.chatbot_id}, trace {request.trace_id}")
        return StreamingResponse(
            run_agent(request, AsyncAgentSession),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error processing message request: {str(e)}")
        # Return an HTTP error response for non-SSE errors
        error_response = ErrorResponse(
            error="Internal Server Error",
            details=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=error_response.to_json()
        )

@app.get("/healthcheck")
async def healthcheck():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    import argparse
    import sys
    import os

    # Add parent directory to path to enable imports
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(parent_dir)

    # Configure argument parser
    parser = argparse.ArgumentParser(description="Run the Async Agent Server API")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="info",
                      choices=["debug", "info", "warning", "error", "critical"],
                      help="Logging level")

    args = parser.parse_args()

    # Configure logging
    log_level = getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run the server
    uvicorn.run(
        "api.agent_server.async_server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level
    )
