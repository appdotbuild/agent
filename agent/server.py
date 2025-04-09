import logging
from typing import AsyncGenerator

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
    ErrorResponse
)
from api.agent_server.interface import AgentInterface

logger = logging.getLogger(__name__)

def get_handler_app[T: AgentInterface](agent_class: type[T]) -> FastAPI:
    async def run_agent(request: AgentRequest, *args, **kwargs) -> AsyncGenerator[str, None]:
        logger.info(f"Creating new agent session for {request.chatbot_id}:{request.trace_id}")
        event_tx, event_rx = anyio.create_memory_object_stream[AgentSseEvent](0)
        agent = agent_class(*args, **kwargs)
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

    app = FastAPI()

    @app.post("/", response_model=None)
    async def process(request: AgentRequest) -> StreamingResponse:
        try:
            logger.info(f"Received message request for chatbot {request.chatbot_id}, trace {request.trace_id}")       
            # Start the SSE stream
            logger.info(f"Starting SSE stream for chatbot {request.chatbot_id}, trace {request.trace_id}")
            return StreamingResponse(run_agent(request), media_type="text/event-stream")
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

    return app
