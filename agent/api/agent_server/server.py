import asyncio
import json
import logging
from typing import Dict, List, Any, AsyncGenerator, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from langfuse import Langfuse

from api.fsm_tools import FSMToolProcessor, run_with_claude
from compiler.core import Compiler
from fsm_core.llm_common import get_sync_client

from .models import (
    AgentRequest, 
    AgentSseEvent, 
    AgentMessage, 
    AgentStatus, 
    MessageKind,
    ErrorResponse
)

logger = logging.getLogger(__name__)

# Global state tracking for active agents
active_agents: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Agent Server API")
    yield

    logger.info("Shutting down Agent Server API")


app = FastAPI(
    title="Agent Server API",
    description="API for communication between the Platform (Backend) and the Agent Server",
    version="1.0.0",
    lifespan=lifespan
)


class AgentSession:
    """Manages a single agent session and its state machine"""
    
    def __init__(self, chatbot_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        """Initialize a new agent session"""
        self.chatbot_id = chatbot_id
        self.trace_id = trace_id
        self.settings = settings or {}
        self.is_running = False
        self.fsm_instance = None
        self.processor_instance = None
        self.langfuse_client = Langfuse()
        self.langfuse_trace = self.langfuse_client.trace(
            id=trace_id,
            name="agent_server",
            user_id=chatbot_id,
            metadata={"agent_controlled": True},
        )
        self.llm_client = get_sync_client()
        self.compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        self._initialize_app()

        
    def _initialize_app(self):
        """Initialize the application instance"""
        self.processor_instance = FSMToolProcessor()
  
    
    def initialize_fsm(self, messages: List[str], agent_state: Optional[Dict[str, Any]] = None):
        """Initialize the FSM with messages and optional state"""
        
        return self.processor_instance.tool_start_fsm(messages.join("\n"), agent_state)
    
    
    def get_state(self) -> Dict[str, Any]:
        """Get the current FSM state"""
        return self.processor_instance.fsm_manager.fsm_instance.context
    
            
    def process_step(self) -> Optional[AgentSseEvent]:
        """Process a single step and return an SSE event"""
        if not self.processor_instance:
            return None
            
        current_messages, is_complete = run_with_claude(self.processor_instance, self.llm_client, messages)
          
       
    def cleanup(self):
        """Cleanup resources for this session"""
        #self.is_running = False
        self.processor_instance = None
        pass


async def get_agent_session(
    chatbot_id: str, 
    trace_id: str, 
    settings: Optional[Dict[str, Any]] = None
) -> AgentSession:
    """Get or create an agent session"""
    session_key = f"{chatbot_id}:{trace_id}"
    
    if session_key not in active_agents:
        logger.info(f"Creating new agent session for {session_key}")
        active_agents[session_key] = AgentSession(chatbot_id, trace_id, settings)
    
    return active_agents[session_key]


async def sse_event_generator(session: AgentSession, messages: List[str], agent_state: Optional[Dict[str, Any]] = None) -> AsyncGenerator[str, None]:
    """Generate SSE events for the agent session"""
    try:
        await run_in_threadpool(session.initialize_fsm, messages, agent_state)
        
        initial_event = await run_in_threadpool(session.process_step)
        if initial_event:
            yield f"data: {json.dumps(initial_event.dict(by_alias=True))}\n\n"
        
        while True:
            should_continue = await run_in_threadpool(session.advance_fsm)
            if not should_continue:
                final_event = await run_in_threadpool(session.process_step)
                if final_event:
                    yield f"data: {json.dumps(final_event.dict(by_alias=True))}\n\n"
                break
            
            event = await run_in_threadpool(session.process_step)
            if event:
                yield f"data: {json.dumps(event.dict(by_alias=True))}\n\n"
            
            if event and event.status == AgentStatus.IDLE:
                break
            
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Error in SSE generator: {str(e)}")
        error_event = AgentSseEvent(
            status=AgentStatus.IDLE,
            traceId=session.trace_id,
            message=AgentMessage(
                kind=MessageKind.RUNTIME_ERROR,
                content=f"Error processing request: {str(e)}",
                agentState=None,
                unifiedDiff=None
            )
        )
        yield f"data: {json.dumps(error_event.dict(by_alias=True))}\n\n"
    finally:
        await run_in_threadpool(session.cleanup)


@app.post("/message", response_model=None)
async def message(request: AgentRequest) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.
    
    The server responds with a stream of Server-Sent Events (SSE).
    Each event contains a JSON payload with status updates.
    """
    try:
        session = await get_agent_session(
            request.chatbot_id, 
            request.trace_id, 
            request.settings
        )
        
        return StreamingResponse(
            sse_event_generator(
                session, 
                request.all_messages, 
                request.agent_state
            ),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.error(f"Error processing message request: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing request: {str(e)}"
        )


@app.get("/healthcheck")
async def healthcheck():
    """Health check endpoint"""
    return {"status": "healthy"}