import enum
from enum import Enum, auto
import dataclasses
from typing import Dict, List, Optional, Any, Literal, Union

# this a pseudocode for API design 

class Application:
    def __init__(self, 
                 compiler: Compiler,
                 llm_client: LLMClient, 
                 langfuse_client: LangfuseClient,
                 config: Config,
                 ):
        self.compiler = compiler
        self.llm_client = llm_client
        self.langfuse_client = langfuse_client
        self.config = config
        self.state_machine = CodegenStateMachine(**config)
        self._callback_url = callback_url
    

    @classmethod
    def from_config(cls, config: Config | str):
        if isinstance(config, str):
            config = Config.from_file(config)
        return cls(
            compiler=Compiler(**config.compiler),
            llm_client=LLMClient(**config.llm_client),
            langfuse_client=LangfuseClient(**config.langfuse_client),
            config=config.codegen
        )
    
    def create_bot(self, initial_prompt: str, callback_url: str) -> Result:
        self._callback_url = callback_url
        state = State.NOT_STARTED
        event = Event(prompt=initial_prompt, category=EventCategory.PROMPT)

        self._callback_url({"state": state})
        while state not in [State.COMPLETED, State.FAILED]:
            state, event = self.state_machine.process_event(event)
            self._callback_url({"state": state, "context": self.state_machine.get_context()})
            if state == State.WAITING_FOR_FEEDBACK:
                promise = self._callback_url({"state": state , "context": self.state_machine.get_context()})
                feedback = promise.wait()
                state, event = self.state_machine.process_event(Event(feedback=feedback, category=EventCategory.FEEDBACK))
        
        if state == State.COMPLETED:
            final_stage = self.state_machine.get_final_result()
            return Result(
                data=final_stage.data,
                metadata=self.state_machine.get_metadata()
            )
        else:
            return Result(
                data=None,
                metadata=self.state_machine.get_metadata(),
                failure_reason=self.state_machine.get_failure_reason()
            )
        
class State(Enum):
    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    WAITING_FOR_FEEDBACK = auto()
    COMPLETED = auto()
    FAILED = auto()

class EventCategory(Enum):
    PROMPT = auto()
    REQUEST_FOR_FEEDBACK = auto()
    FEEDBACK = auto()
    REQUEST_FOR_CORRECTION = auto()
    SUCCESS = auto()
    FAILURE = auto()

class Event:
    category: EventCategory
    prompt: str | None = None
    context: Dict[str, Any] | None = None
    feedback: Dict[str, Any] | None = None


class Result:
    data: Optional[Any] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    failure_reason: Optional[str] = None


class CodegenStateMachine:
    def __init__(self, config: Config):
        self.config = config
        self.state = State.NOT_STARTED
        self.event = None
        self.context = {}
        self.data = {}

        self.histoty = ...
        self.statistics = ...

    def process_event(self, event: Event) -> Tuple[State, Event]:

        match self.state, self.event.category:
            case State.NOT_STARTED, EventCategory.PROMPT:
                self.state = State.IN_PROGRESS
                self.context['prompt'] = event.prompt
                self.context.update(event.context)
            case State.IN_PROGRESS, EventCategory.REQUEST_FOR_FEEDBACK:
                self.state = State.WAITING_FOR_FEEDBACK
            case State.WAITING_FOR_FEEDBACK, EventCategory.FEEDBACK:
                self.state = State.IN_PROGRESS
                self.context['feedback'] = event.feedback
            case State.IN_PROGRESS, EventCategory.SUCCESS:
                # run next stage 
                self.state = State.IN_PROGRESS
            case _, EventCategory.FAILURE:
                self.state = State.FAILED
                self.failure_reason = event.failure_reason
            case _:
                raise ValueError(f"unexpected event {event.category} in state {self.state}")
        
        
    def get_context(self) -> Dict[str, Any]:
        return self.context

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "history": self.history,
            "statistics": self.statistics
        }


