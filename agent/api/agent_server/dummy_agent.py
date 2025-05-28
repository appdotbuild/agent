"""
Dummy agent implementation for debugging SSE with varying event sizes.
This agent doesn't require Dagger connections.
"""
import json
import random
import string
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectSendStream

from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind,
)
from log import get_logger

logger = get_logger(__name__)


class DummyAgent:
    """Dummy agent that sends 100 SSE events with varying sizes for debugging."""

    def __init__(self, application_id: str, trace_id: str, settings: dict[str, Any] | None = None, **kwargs):
        self.application_id = application_id
        self.trace_id = trace_id
        self.settings = settings or {}
        logger.info(f"Initialized DummyAgent for {application_id}:{trace_id}")

    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """Process the request by sending 100 SSE events with varying sizes."""
        logger.info(f"DummyAgent processing request for {self.application_id}:{self.trace_id}")

        try:
            # Send initial message
            start_event = AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.STAGE_RESULT,
                    content="Starting dummy agent - will send 100 events with varying sizes",
                    agentState={},
                    unifiedDiff=""
                )
            )
            await event_tx.send(start_event)

            # Send 100 events with varying sizes
            for i in range(100):
                # determine event size
                if i % 10 < 3:  # 30% of events are large (1-3MB)
                    size_mb = random.uniform(1, 3)
                    size_bytes = int(size_mb * 1024 * 1024)
                    content_data = ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes))
                    event_type = "large"
                else:  # 70% of events are small
                    size_bytes = random.randint(100, 10000)
                    content_data = ''.join(random.choices(string.ascii_letters + string.digits, k=size_bytes))
                    event_type = "small"

                # create event content
                event_content = {
                    "event_number": i + 1,
                    "event_type": event_type,
                    "size_bytes": len(content_data),
                    "size_mb": round(len(content_data) / (1024 * 1024), 3),
                    "content": content_data
                }

                logger.info(f"Sending event {i + 1}/100: {event_type} ({len(content_data)} bytes)")

                # send as agent message
                event = AgentSseEvent(
                    status=AgentStatus.RUNNING,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        role="assistant",
                        kind=MessageKind.STAGE_RESULT,
                        content=json.dumps(event_content),
                        agentState={"event_count": i + 1, "total_events": 100},
                        unifiedDiff=""
                    )
                )
                await event_tx.send(event)

                # small delay to simulate real-time streaming
                await anyio.sleep(0.01)

                logger.debug(f"Sent event {i + 1}/100 ({event_type}, {len(content_data)} bytes)")

            # send completion message
            completion_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.REVIEW_RESULT,
                    content="Dummy agent completed - sent 100 events",
                    agentState={},
                    unifiedDiff=""
                )
            )
            await event_tx.send(completion_event)

            logger.info(f"DummyAgent completed processing for {self.application_id}:{self.trace_id}")

        except Exception as e:
            logger.exception(f"Error in DummyAgent processing: {e}")
            error_event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    role="assistant",
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"DummyAgent error: {str(e)}",
                    agentState={},
                    unifiedDiff=""
                )
            )
            await event_tx.send(error_event)
        finally:
            await event_tx.aclose()
