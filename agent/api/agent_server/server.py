import json
import logging
import asyncio
import uuid
from typing import Dict, List, Any, AsyncGenerator, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from langfuse import Langfuse

from application import Application, InteractionMode, FsmEvent, FsmState
from compiler.core import Compiler
from statemachine import StateMachine
from fsm_core.llm_common import get_sync_client

from .models import (
    AgentRequest, 
    AgentSseEvent, 
    AgentMessage, 
    AgentStatus, 
    MessageKind,
    ErrorResponse
)

# Configure logging
logger = logging.getLogger(__name__)

# Global state tracking for active agents
active_agents: Dict[str, Dict[str, Any]] = {}

# FastAPI app lifespan context
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize clients and resources
    logger.info("Initializing Agent Server API")
    yield
    # Clean up resources
    logger.info("Shutting down Agent Server API")

# Create FastAPI app
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
        self.app_instance = None
        self.langfuse_client = Langfuse()
        self.langfuse_trace = self.langfuse_client.trace(
            id=trace_id,
            name="agent_server",
            user_id=chatbot_id,
            metadata={"agent_controlled": True},
        )
        self.aws_client = get_sync_client()
        self.compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
        self._initialize_app()
        
    def _initialize_app(self):
        """Initialize the application instance"""
        # Extract settings
        max_iterations = self.settings.get("max-iterations", 3)
        
        # Create application with appropriate settings
        self.app_instance = Application(
            client=self.aws_client,
            compiler=self.compiler,
            langfuse_client=self.langfuse_client,
            interaction_mode=InteractionMode.INTERACTIVE
        )
    
    def initialize_fsm(self, messages: List[str], agent_state: Optional[Dict[str, Any]] = None):
        """Initialize the FSM with messages and optional state"""
        if self.is_running:
            raise RuntimeError(f"Agent session {self.trace_id} is already running")
            
        self.is_running = True
        
        try:
            # Initialize FSM context with user messages
            fsm_context = {
                "user_requests": messages
            }
            
            # If we have agent state, restore it
            if agent_state:
                # Merge the agent state into the context
                fsm_context.update(agent_state)
            
            logger.debug(f"Creating FSM states for session {self.trace_id}")
            fsm_states = self.app_instance.make_fsm_states(
                trace_id=self.trace_id,
                observation_id=self.trace_id
            )
            
            logger.debug(f"Initializing StateMachine for session {self.trace_id}")
            self.fsm_instance = StateMachine[Dict[str, Any]](fsm_states, fsm_context)
            
            # Only send PROMPT event if no agent state (new conversation)
            if not agent_state:
                logger.info(f"Sending initial PROMPT event to FSM for session {self.trace_id}")
                self.fsm_instance.send(FsmEvent(type_="PROMPT"))
                
            return True
            
        except Exception as e:
            self.is_running = False
            logger.error(f"Error initializing FSM for session {self.trace_id}: {str(e)}")
            raise
    
    def get_state(self) -> Dict[str, Any]:
        """Get the current FSM state"""
        if not self.fsm_instance:
            return {"error": "No FSM instance available"}
            
        current_state = self.fsm_instance.stack_path[-1]
        context = self.fsm_instance.context
        
        # Extract the minimal state to send back
        agent_state = {k: v for k, v in context.items() if k not in ["error", "last_transition"]}
        
        return {
            "current_state": current_state,
            "agent_state": agent_state
        }
        
    def process_step(self) -> Optional[AgentSseEvent]:
        """Process a single step and return an SSE event"""
        if not self.fsm_instance:
            return None
            
        current_state = self.fsm_instance.stack_path[-1]
        
        # Check if FSM is in a final state
        if current_state in [FsmState.COMPLETE, FsmState.FAILURE]:
            # Extract appropriate response
            if current_state == FsmState.FAILURE:
                error_msg = self.fsm_instance.context.get("error", "Unknown error")
                return AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        kind=MessageKind.RUNTIME_ERROR,
                        content=f"Agent encountered an error: {error_msg}",
                        agentState=self.get_state()["agent_state"],
                        unifiedDiff=None
                    )
                )
            else:
                # Complete state
                return AgentSseEvent(
                    status=AgentStatus.IDLE,
                    traceId=self.trace_id,
                    message=AgentMessage(
                        kind=MessageKind.FEEDBACK_RESPONSE,
                        content="All done. Code is available.",
                        agentState=self.get_state()["agent_state"],
                        unifiedDiff=None  # TODO: Implement diff extraction
                    )
                )
                
        # Check if FSM is in a review state (needs feedback)
        if current_state in [
            FsmState.TYPESPEC_REVIEW, 
            FsmState.DRIZZLE_REVIEW, 
            FsmState.TYPESCRIPT_REVIEW,
            FsmState.HANDLER_TESTS_REVIEW, 
            FsmState.HANDLERS_REVIEW
        ]:
            # Extract state output for review
            output = self._get_state_output(current_state)
            
            return AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=AgentMessage(
                    kind=MessageKind.FEEDBACK_RESPONSE,
                    content=output.get("reasoning", "Ready for review. Please provide feedback."),
                    agentState=self.get_state()["agent_state"],
                    unifiedDiff=None  # TODO: Extract any relevant diffs
                )
            )
            
        # For processing states, send a StageResult
        return AgentSseEvent(
            status=AgentStatus.RUNNING,
            traceId=self.trace_id,
            message=AgentMessage(
                kind=MessageKind.STAGE_RESULT,
                content=f"Processing step: {current_state}",
                agentState=self.get_state()["agent_state"],
                unifiedDiff=None
            )
        )
            
    def advance_fsm(self, feedback: Optional[str] = None) -> bool:
        """Advance the FSM to the next state"""
        if not self.fsm_instance:
            return False
            
        current_state = self.fsm_instance.stack_path[-1]
        
        try:
            if current_state in [
                FsmState.TYPESPEC_REVIEW, 
                FsmState.DRIZZLE_REVIEW, 
                FsmState.TYPESCRIPT_REVIEW,
                FsmState.HANDLER_TESTS_REVIEW, 
                FsmState.HANDLERS_REVIEW
            ] and feedback:
                # Send appropriate revision event
                event_type = self._get_revision_event_type(current_state)
                if event_type:
                    self.fsm_instance.send(FsmEvent(event_type, feedback))
                    return True
            elif current_state not in [FsmState.COMPLETE, FsmState.FAILURE]:
                # Confirm current state if not in a terminal state
                self.fsm_instance.send(FsmEvent(type_="CONFIRM"))
                return True
                
            return False
            
        except Exception as e:
            logger.error(f"Error advancing FSM: {str(e)}")
            return False
    
    def _get_revision_event_type(self, state: str) -> Optional[str]:
        """Map review state to corresponding revision event type"""
        event_map = {
            FsmState.TYPESPEC_REVIEW: FsmEvent.REVISE_TYPESPEC,
            FsmState.DRIZZLE_REVIEW: FsmEvent.REVISE_DRIZZLE,
            FsmState.TYPESCRIPT_REVIEW: FsmEvent.REVISE_TYPESCRIPT,
            FsmState.HANDLER_TESTS_REVIEW: FsmEvent.REVISE_HANDLER_TESTS,
            FsmState.HANDLERS_REVIEW: FsmEvent.REVISE_HANDLERS
        }
        return event_map.get(state)
    
    def _get_state_output(self, current_state: str) -> Dict[str, Any]:
        """Extract relevant output for the current state"""
        context = self.fsm_instance.context
        
        try:
            match current_state:
                case FsmState.TYPESPEC_REVIEW:
                    if "typespec_schema" in context:
                        return {
                            "typespec": context["typespec_schema"].typespec,
                            "reasoning": context["typespec_schema"].reasoning
                        }
                
                case FsmState.DRIZZLE_REVIEW:
                    if "drizzle_schema" in context:
                        return {
                            "drizzle_schema": context["drizzle_schema"].drizzle_schema,
                            "reasoning": context["drizzle_schema"].reasoning
                        }
                
                case FsmState.TYPESCRIPT_REVIEW:
                    if "typescript_schema" in context:
                        return {
                            "typescript_schema": context["typescript_schema"].typescript_schema,
                            "reasoning": context["typescript_schema"].reasoning
                        }
                
                case FsmState.HANDLER_TESTS_REVIEW:
                    if "handler_tests" in context:
                        return {
                            "handler_tests": {
                                name: {"source": test.source}
                                for name, test in context["handler_tests"].items()
                            }
                        }
                
                case FsmState.HANDLERS_REVIEW:
                    if "handlers" in context:
                        return {
                            "handlers": {
                                name: {"source": handler.source if hasattr(handler, "source") else str(handler)}
                                for name, handler in context["handlers"].items()
                            }
                        }
                
                case _:
                    return {"status": "processing"}
        except Exception as e:
            logger.error(f"Error getting state output: {str(e)}")
            return {"status": "error", "message": f"Error retrieving state output: {str(e)}"}
        
        return {"status": "processing"}
        
    def cleanup(self):
        """Cleanup resources for this session"""
        self.is_running = False
        self.fsm_instance = None
        # Clean other resources if needed


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
        # Initialize FSM if needed
        await run_in_threadpool(session.initialize_fsm, messages, agent_state)
        
        # Initial status event
        initial_event = await run_in_threadpool(session.process_step)
        if initial_event:
            yield f"data: {json.dumps(initial_event.dict(by_alias=True))}\n\n"
        
        # Process until idle or error
        while True:
            # Advance FSM
            should_continue = await run_in_threadpool(session.advance_fsm)
            if not should_continue:
                # Get final state
                final_event = await run_in_threadpool(session.process_step)
                if final_event:
                    yield f"data: {json.dumps(final_event.dict(by_alias=True))}\n\n"
                break
            
            # Get current state and send event
            event = await run_in_threadpool(session.process_step)
            if event:
                yield f"data: {json.dumps(event.dict(by_alias=True))}\n\n"
            
            # If idle, stop
            if event and event.status == AgentStatus.IDLE:
                break
            
            # Add a small delay to prevent CPU spinning
            await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Error in SSE generator: {str(e)}")
        # Send error event
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
        # Cleanup session
        await run_in_threadpool(session.cleanup)


@app.post("/message", response_model=None)
async def message(request: AgentRequest) -> StreamingResponse:
    """
    Send a message to the agent and stream responses via SSE.
    
    The server responds with a stream of Server-Sent Events (SSE).
    Each event contains a JSON payload with status updates.
    """
    try:
        # Get or create agent session
        session = await get_agent_session(
            request.chatbot_id, 
            request.trace_id, 
            request.settings
        )
        
        # Return streaming response
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