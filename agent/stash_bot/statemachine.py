from typing import Any, Awaitable, Callable, NotRequired, Protocol, TypedDict
import logging

logger = logging.getLogger(__name__)


class Actor(Protocol):
    async def execute(self, *args, **kwargs) -> Any:
        ...


class InvokeCallback[T](TypedDict):
    target: str
    actions: NotRequired[list[Callable[[T, Any], Awaitable[Any]]]] # = []


class Invoke[T](TypedDict):
    src: Actor
    input_fn: Callable[[T], Any]
    on_done: NotRequired[InvokeCallback[T]]
    on_error: NotRequired[InvokeCallback[T]]


class AlwaysRun[T](TypedDict):
    target: str
    guard: NotRequired[Callable[[T], Awaitable[bool]]]
    actions: NotRequired[list[Callable[[T], Awaitable[Any]]]]


class State[T](TypedDict):
    entry: NotRequired[list[Callable[[T], Awaitable[Any]]]]
    invoke: NotRequired[Invoke[T]]
    on: NotRequired[dict[str, str]]
    exit: NotRequired[list[Callable[[T], Awaitable[Any]]]]
    always: NotRequired[AlwaysRun[T] | list[AlwaysRun[T]]]
    states: NotRequired[dict[str, "State[T]"]]
    initial: NotRequired[str]


class StateMachine[T]:
    def __init__(self, root: State, context: T):
        self.root = root
        self.context = context
        self.state_stack: list[State[T]] = [root]
        self._queued_transition: str | None = None

    async def send(self, event):
        # Handle both string events and FsmEvent objects
        event_type = event.type if hasattr(event, "type") else event

        logger.info(f"Received event: {event_type}")

        for state in reversed(self.state_stack):
            if "on" in state and event_type in state["on"]:
                # Store feedback in context if available
                if hasattr(event, "feedback") and event.feedback is not None:
                    self._store_feedback(event)

                self._queued_transition = state["on"][event_type]
                logger.info(f"Queuing transition to: {self._queued_transition}")
                await self._process_transitions()
                return
        raise RuntimeError(f"Invalid event: {event_type}, stack: {self.stack_path}")

    def _store_feedback(self, event):
        """Store feedback from the event in the context."""
        if not hasattr(event, "feedback") or event.feedback is None:
            return

        # Map event types to context keys
        if event.type == "REVISE_TYPESPEC":
            self.context["typespec_feedback"] = event.feedback
        elif event.type == "REVISE_DRIZZLE":
            self.context["drizzle_feedback"] = event.feedback
        elif event.type == "REVISE_TYPESCRIPT":
            self.context["typescript_feedback"] = event.feedback
        elif event.type == "REVISE_HANDLER_TESTS" and isinstance(event.feedback, dict):
            # Create or update the handler_tests_feedback dictionary
            handler_tests_feedback = self.context.get("handler_tests_feedback", {})
            handler_tests_feedback.update(event.feedback)
            self.context["handler_tests_feedback"] = handler_tests_feedback
        elif event.type == "REVISE_HANDLERS" and isinstance(event.feedback, dict):
            # Create or update the handlers_feedback dictionary
            handlers_feedback = self.context.get("handlers_feedback", {})
            handlers_feedback.update(event.feedback)
            self.context["handlers_feedback"] = handlers_feedback

    async def _process_transitions(self):
        while self._queued_transition:
            logger.info(f"Processing transition: path={self.stack_path}, target={self._queued_transition}")
            next_state = self._queued_transition
            self._queued_transition = None
            await self._transition(next_state)

    async def _transition(self, next_state: str):
        exit_stack = []
        logger.info(f"Transitioning to state: {next_state}")
        while self.state_stack:
            parent_state = self.state_stack.pop()
            if "states" not in parent_state or next_state not in parent_state["states"]:
                exit_stack.append(parent_state)
                continue
            target_state = parent_state["states"][next_state]
            for state in reversed(exit_stack):
                await self._run_exit(state)
            await self._run_entry(target_state)
            await self._run_invoke(target_state)
            await self._run_always(target_state)
            self.state_stack.extend([parent_state, target_state]) # put target state on stack
            # Get updated path including the current state
            path = [next_state]
            logger.info(f"Transitioned to: {next_state}, new path={path}")
            return
        self.state_stack.extend(reversed(exit_stack)) # restore stack
        raise RuntimeError(f"Invalid transition: {next_state}, stack: {self.stack_path}")

    @property
    def stack_path(self) -> list[str]:
        """
        Calculate the path of states in the stack.
        Note: This method only returns the raw path - application-specific error handling
        should be done at the application level.
        """
        if not self.state_stack:
            return []

        path = []
        # Process state pairs to find transitions
        for p, n in zip(self.state_stack, self.state_stack[1:]):
            if "states" not in p:
                break
            for key, value in p["states"].items():
                if value == n:
                    path.append(key)
                    break

        return path

    async def _run_entry(self, state: State[T]):
        if "entry" in state:
            logger.info("Running entry actions")
            for action in state["entry"]:
                action_name = action.__name__ if hasattr(action, "__name__") else "unknown"
                logger.info(f"Running entry action: {action_name}")
                await action(self.context)

    async def _run_exit(self, state: State[T]):
        if "exit" in state:
            logger.info("Running exit actions")
            for action in state["exit"]:
                action_name = action.__name__ if hasattr(action, "__name__") else "unknown"
                logger.info(f"Running exit action: {action_name}")
                await action(self.context)

    async def _run_invoke(self, state: State[T]):
        if "invoke" in state:
            invoke = state["invoke"]
            actor_name = invoke["src"].__class__.__name__ if hasattr(invoke["src"], "__class__") else "Unknown"
            logger.info(f"Executing actor: {actor_name}")
            try:
                try:
                    args = invoke["input_fn"](self.context)
                except Exception:
                    exit()

                logger.info(f"Actor {actor_name} executing with args {args}")
                event = await invoke["src"].execute(*args)
                logger.info(f"Actor {actor_name} execution completed successfully")
                if "on_done" in invoke:
                    self._queued_transition = invoke["on_done"]["target"]
                    logger.info(f"Actor {actor_name} success: queuing transition to {self._queued_transition}")
                    for action in invoke["on_done"].get("actions", []):
                        await action(self.context, event)
            except Exception as e:
                # Log the detailed error information
                logger.exception(f"Actor {actor_name} execution failed")

                # Store the full error information in context regardless of on_error handlers
                # This ensures error details are preserved even during failure transitions
                if "error" not in self.context:
                    self.context["error"] = str(e)

                # Also store the actor where failure happened for debugging
                self.context["failed_actor"] = actor_name

                if "on_error" in invoke:
                    self._queued_transition = invoke["on_error"]["target"]
                    logger.info(f"Actor {actor_name} failure: queuing transition to {self._queued_transition}")
                    for action in invoke["on_error"].get("actions", []):
                        await action(self.context, e)
                else:
                    raise e

    async def _run_always(self, state: State[T]):
        if "always" in state:
            logger.info("Checking always transitions")
            branches = state["always"] if isinstance(state["always"], list) else [state["always"]]
            for always in branches:
                if "guard" not in always:
                    logger.info(f"No guard, taking transition to {always['target']}")
                    self._queued_transition = always["target"]
                    for action in always.get("actions", []):
                        action_name = action.__name__ if hasattr(action, "__name__") else "unknown"
                        logger.info(f"Running always action: {action_name}")
                        await action(self.context)
                    return
                elif await always["guard"](self.context):
                    guard_name = always["guard"].__name__ if hasattr(always["guard"], "__name__") else "unknown"
                    logger.info(f"Guard {guard_name} passed, taking transition to {always['target']}")
                    self._queued_transition = always["target"]
                    for action in always.get("actions", []):
                        action_name = action.__name__ if hasattr(action, "__name__") else "unknown"
                        logger.info(f"Running always action: {action_name}")
                        await action(self.context)
                    return
                else:
                    guard_name = always["guard"].__name__ if hasattr(always["guard"], "__name__") else "unknown"
                    logger.info(f"Guard {guard_name} failed, not taking transition")
