"""
FastAPI implementation for the agent server.

This server handles API requests initiated by clients (e.g., test clients),
coordinates agent logic using components from `core` and specific agent
implementations like `trpc_agent`. It utilizes `models.py` for
request/response validation and interacts with LLMs via the `llm` wrappers
(indirectly through agents).

Refer to `architecture.puml` for a visual overview.
"""
from typing import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import uvicorn
from fire import Fire
import dagger
import sys

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
    ErrorResponse
)
from api.agent_server.interface import AgentInterface
from trpc_agent.agent_session import AsyncAgentSession as TrpcAgentSession
from api.agent_server.template_diff_impl import TemplateDiffAgentImplementation
from api.config import CONFIG

from log import get_logger, init_sentry

logger = get_logger(__name__)

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
bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    valid_token = CONFIG.builder_token
    if not valid_token:
        logger.info("No token configured, skipping authentication")
        return True

    if not credentials or not credentials.scheme == "Bearer":
        logger.info("Missing authentication token")
        raise HTTPException(
            status_code=401,
            detail="Unauthorized - missing authentication token"
        )

    if credentials.scheme.lower() != "bearer" or credentials.credentials != valid_token:
        logger.info("Invalid authentication token")
        raise HTTPException(
            status_code=403,
            detail="Unauthorized - invalid authentication token"
        )

    return True


class SessionManager:
    def __init__(self):
        self.sessions = {}

    def get_or_create_session[T: AgentInterface](
        self,
        request: AgentRequest,
        agent_class: type[T],
        *args,
        **kwargs
    ) -> T:
        session_id = f"{request.application_id}:{request.trace_id}"

        if session_id in self.sessions:
            logger.info(f"Reusing existing session for {session_id}")
            return self.sessions[session_id]

        logger.info(f"Creating new agent session for {session_id}")
        agent = agent_class(
            application_id=request.application_id,
            trace_id=request.trace_id,
            settings=request.settings,
            *args,
            **kwargs
        )
        self.sessions[session_id] = agent
        return agent

    def cleanup_session(self, application_id: str, trace_id: str) -> None:
        session_id = f"{application_id}:{trace_id}"
        if session_id in self.sessions:
            logger.info(f"Removing session for {session_id}")
            del self.sessions[session_id]

session_manager = SessionManager()

async def run_agent[T: AgentInterface](
    request: AgentRequest,
    agent_class: type[T],
    *args,
    **kwargs,
) -> AsyncGenerator[str, None]:
    logger.info(f"Running agent for session {request.application_id}:{request.trace_id}")
    
    async with dagger.connection(dagger.Config(log_output=sys.stderr)):
        agent = session_manager.get_or_create_session(request, agent_class, *args, **kwargs)

        event_tx, event_rx = anyio.create_memory_object_stream[AgentSseEvent](max_buffer_size=0)
        final_state = None

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(agent.process, request, event_tx)
                async with event_rx:
                    async for event in event_rx:
                        if event.message and event.message.agent_state:
                            final_state = event.message.agent_state

                        yield f"data: {event.to_json()}\n\n"

                        if event.status == AgentStatus.IDLE and request.agent_state is None:
                            logger.info(f"Agent idle, will clean up session for {request.application_id}:{request.trace_id}")

        except* Exception as excgroup:
            for e in excgroup.exceptions:
                logger.exception(f"Error in SSE generator TaskGroup for trace {request.trace_id}:", exc_info=e)
                error_event = AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=request.trace_id,
                    message=AgentMessage(
                        role="agent",
                        kind=MessageKind.RUNTIME_ERROR,
                        content=f"Error processing request: {str(e)}", # Keep simple message for client
                        agentState=None,
                        unifiedDiff=""
                    )
                )
                yield f"data: {error_event.to_json()}\n\n"

                session_manager.cleanup_session(request.application_id, request.trace_id)
        finally:
            if request.agent_state is None and (final_state is None or final_state == {}):
                logger.info(f"Cleaning up completed agent session for {request.application_id}:{request.trace_id}")
                session_manager.cleanup_session(request.application_id, request.trace_id)


@app.post("/message", response_model=None)
async def message(
    request: AgentRequest,
    token: str = Depends(verify_token)
) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.

    Platform (Backend) -> Agent Server API Spec:
    POST Request:
    - allMessages: [str] - history of all user messages
    - applicationId: str - required for Agent Server for tracing
    - traceId: str - required - a string used in SSE events
    - agentState: {..} or null - the full state of the Agent to restore from
    - settings: {...} - json with settings with number of iterations etc

    SSE Response:
    - status: "running" | "idle" - defines if the Agent stopped or continues running
    - traceId: corresponding traceId of the input
    - message: {kind, content, agentState, unifiedDiff} - response from the Agent Server

    Args:
        request: The agent request containing all necessary fields
        token: Authentication token (automatically verified by verify_token dependency)

    Returns:
        Streaming response with SSE events according to the API spec
    """
    try:
        logger.info(f"Received message request for application {request.application_id}, trace {request.trace_id}")

        logger.info(f"Starting SSE stream for application {request.application_id}, trace {request.trace_id}")
        agent_type = {
            "trpc_agent": TrpcAgentSession,
            "template_diff": TemplateDiffAgentImplementation,
        }
        return StreamingResponse(
            run_agent(request, agent_type[CONFIG.agent_type]),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Error processing message request: {str(e)}")
        error_response = ErrorResponse(
            error="Internal Server Error",
            details=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=error_response.to_json()
        )

@app.get("/health")
async def healthcheck():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {"status": "healthy"}


@app.get("/health/dagger")
async def dagger_healthcheck():
    """Dagger connection health check endpoint"""
    async with dagger.Connection() as client:
        container = client.container().from_("alpine:latest")
        version = await container.with_exec(["cat", "/etc/alpine-release"]).stdout()
        return {
            "status": "healthy",
            "dagger_connection": "successful",
            "alpine_version": version.strip()
        }


def main(
    host: str = "0.0.0.0",
    port: int = 8001,
    reload: bool = False,
    log_level: str = "info"
):
    init_sentry()
    uvicorn.run(
        "trpc_agent.async_server:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )

if __name__ == "__main__":
    Fire(main)
