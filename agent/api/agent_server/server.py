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
from api.fsm_api import FSMManager
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
        self.is_complete = False
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
        logger.info(f"Initializing application for trace {self.trace_id}")
        self.fsm_api = FSMManager()
        self.processor_instance = FSMToolProcessor(self.fsm_api)
        self.messages = []
        logger.info(f"Application initialized for trace {self.trace_id}")
    
    
    def initialize_fsm(self, messages: List[str], agent_state: Optional[Dict[str, Any]] = None):
        """Initialize the FSM with messages and optional state"""
        logger.info(f"Initializing FSM for trace {self.trace_id}")
        logger.debug(f"Agent state present: {agent_state is not None}")
        
        if agent_state:
            logger.info(f"Setting external state for trace {self.trace_id}")
            self.fsm_api.set_full_external_state(agent_state)

        #TODO: Avoid merging messages with the app description
        app_description = "\n".join(messages)
        logger.debug(f"App description length: {len(app_description)}")
        self.messages = [{"role": "user", "content": app_description}]
        
        logger.info(f"Starting FSM for trace {self.trace_id}")
        result = self.processor_instance.tool_start_fsm(app_description)
        logger.info(f"FSM started for trace {self.trace_id}")
        return result
    
    
    def get_state(self) -> Dict[str, Any]:
        """Get the current FSM state"""
        try:
            logger.debug(f"Getting state for trace {self.trace_id}")
            return self.fsm_api.get_full_external_state()
        except Exception as e:
            logger.error(f"Error getting state for trace {self.trace_id}: {str(e)}")
            return {}
    
            
    def process_step(self) -> Optional[AgentSseEvent]:
        """Process a single step and return an SSE event"""
        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return None
        
        try:
            logger.info(f"Processing step for trace {self.trace_id}")
            new_message, is_complete, _ = run_with_claude(self.processor_instance, self.llm_client, self.messages)
            self.is_complete = is_complete

            if new_message:
                self.messages.append(new_message)
                status = AgentStatus.IDLE if is_complete else AgentStatus.RUNNING
                logger.info(f"Step completed for trace {self.trace_id}. Status: {status}")
                
                return AgentSseEvent(
                    status=status,
                    trace_id=self.trace_id,
                    message=AgentMessage(
                        kind=MessageKind.STAGE_RESULT,
                        content=new_message["content"],
                        agent_state=self.get_state(),
                        unified_diff=None
                    )
                )
            
            logger.info(f"No new message generated for trace {self.trace_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error in process_step: {str(e)}")
            self.is_complete = True
            return AgentSseEvent(
                status=AgentStatus.IDLE,
                trace_id=self.trace_id,
                message=AgentMessage(
                    kind=MessageKind.RUNTIME_ERROR,
                    content=f"Error processing step: {str(e)}",
                    agent_state=None,
                    unified_diff=None
                )
            )


    def advance_fsm(self) -> bool:
        """
        Advance the FSM state. Returns True if more steps are needed,
        False if the FSM is complete or has reached a terminal state.
        """
        if self.is_complete:
            logger.info(f"FSM is already complete for trace {self.trace_id}")
            return False
            
        if not self.processor_instance:
            logger.warning(f"No processor instance found for trace {self.trace_id}")
            return False
            
        logger.info(f"FSM should continue for trace {self.trace_id}")
        return True

        
    def cleanup(self):
        """Cleanup resources for this session"""
        logger.info(f"Cleaning up resources for trace {self.trace_id}")
        self.processor_instance = None
        self.fsm_api = None
        self.messages = []
        logger.info(f"Resources cleaned up for trace {self.trace_id}")


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
        logger.info(f"Initializing FSM for trace {session.trace_id}")
        await run_in_threadpool(session.initialize_fsm, messages, agent_state)
        
        logger.info(f"Processing initial step for trace {session.trace_id}")
        initial_event = await run_in_threadpool(session.process_step)
        if initial_event:
            logger.info(f"Sending initial event for trace {session.trace_id}")
            yield f"data: {json.dumps(initial_event.dict(by_alias=True))}\n\n"
        
        while True:
            logger.info(f"Checking if FSM should continue for trace {session.trace_id}")
            should_continue = await run_in_threadpool(session.advance_fsm)
            if not should_continue:
                logger.info(f"FSM complete, processing final step for trace {session.trace_id}")
                final_event = await run_in_threadpool(session.process_step)
                if final_event:
                    logger.info(f"Sending final event for trace {session.trace_id}")
                    yield f"data: {json.dumps(final_event.dict(by_alias=True))}\n\n"
                break
            
            logger.info(f"Processing next step for trace {session.trace_id}")
            event = await run_in_threadpool(session.process_step)
            if event:
                logger.info(f"Sending event with status {event.status} for trace {session.trace_id}")
                yield f"data: {json.dumps(event.dict(by_alias=True))}\n\n"
            
            if event and event.status == AgentStatus.IDLE:
                logger.info(f"Agent is idle, stopping event stream for trace {session.trace_id}")
                break
            
            await asyncio.sleep(0.1)
            
    except Exception as e:
        logger.error(f"Error in SSE generator: {str(e)}")
        error_event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id=session.trace_id,
            message=AgentMessage(
                kind=MessageKind.RUNTIME_ERROR,
                content=f"Error processing request: {str(e)}",
                agent_state=None,
                unified_diff=None
            )
        )
        logger.error(f"Sending error event for trace {session.trace_id}")
        yield f"data: {json.dumps(error_event.dict(by_alias=True))}\n\n"
    finally:
        logger.info(f"Cleaning up session for trace {session.trace_id}")
        await run_in_threadpool(session.cleanup)


@app.post("/message", response_model=None)
async def message(request: AgentRequest) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.
    
    The server responds with a stream of Server-Sent Events (SSE).
    Each event contains a JSON payload with status updates.
    """
    try:
        logger.info(f"Received message request for chatbot {request.chatbot_id}, trace {request.trace_id}")
        logger.debug(f"Request settings: {request.settings}")
        logger.debug(f"Number of messages: {len(request.all_messages)}")
        
        session = await get_agent_session(
            request.chatbot_id, 
            request.trace_id, 
            request.settings
        )
        
        logger.info(f"Starting SSE stream for chatbot {request.chatbot_id}, trace {request.trace_id}")
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
    logger.debug("Health check requested")
    return {"status": "healthy"}