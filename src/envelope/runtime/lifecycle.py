"""
Lifecycle State Machine (E2)

Manages model lifecycle transitions with validation.
Ensures models go through proper warming before serving.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Awaitable

from envelope.types import LifecycleState


class LifecycleEvent(Enum):
    """Events that trigger lifecycle transitions."""
    LOAD = auto()
    LOAD_COMPLETE = auto()
    WARM = auto()
    WARM_COMPLETE = auto()
    WARM_FAILED = auto()
    START_SERVING = auto()
    DRAIN = auto()
    DRAIN_COMPLETE = auto()
    STOP = auto()
    FAIL = auto()
    RECOVER = auto()


@dataclass
class TransitionRecord:
    """Record of a lifecycle transition."""
    from_state: LifecycleState
    to_state: LifecycleState
    event: LifecycleEvent
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        current_state: LifecycleState,
        event: LifecycleEvent,
        message: str = "",
    ):
        self.current_state = current_state
        self.event = event
        msg = f"Invalid transition: {current_state.name} + {event.name}"
        if message:
            msg += f" - {message}"
        super().__init__(msg)


# State transition table
TRANSITIONS: dict[LifecycleState, dict[LifecycleEvent, LifecycleState]] = {
    LifecycleState.INIT: {
        LifecycleEvent.LOAD: LifecycleState.LOADING,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.LOADING: {
        LifecycleEvent.LOAD_COMPLETE: LifecycleState.WARMING,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.WARMING: {
        LifecycleEvent.WARM_COMPLETE: LifecycleState.READY,
        LifecycleEvent.WARM_FAILED: LifecycleState.FAILED,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.READY: {
        LifecycleEvent.START_SERVING: LifecycleState.SERVING,
        LifecycleEvent.STOP: LifecycleState.STOPPED,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.SERVING: {
        LifecycleEvent.DRAIN: LifecycleState.DRAINING,
        LifecycleEvent.STOP: LifecycleState.STOPPED,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.DRAINING: {
        LifecycleEvent.DRAIN_COMPLETE: LifecycleState.STOPPED,
        LifecycleEvent.FAIL: LifecycleState.FAILED,
    },
    LifecycleState.STOPPED: {
        LifecycleEvent.LOAD: LifecycleState.LOADING,
    },
    LifecycleState.FAILED: {
        LifecycleEvent.RECOVER: LifecycleState.INIT,
        LifecycleEvent.LOAD: LifecycleState.LOADING,
    },
}


# Callback type for state transitions
TransitionCallback = Callable[[LifecycleState, LifecycleState, LifecycleEvent], Awaitable[None]]


class LifecycleStateMachine:
    """
    State machine for model lifecycle management.

    States:
    - INIT: Initial state before loading
    - LOADING: Model is being loaded into memory
    - WARMING: Model is warming up (running golden tests)
    - READY: Model is ready to serve (passed warming)
    - SERVING: Model is actively serving requests
    - DRAINING: Model is draining existing requests before stop
    - STOPPED: Model is stopped and unloaded
    - FAILED: Model encountered an error

    Transitions are validated against the transition table.
    The WARMING state is mandatory - models must pass golden
    tests before entering READY state.
    """

    def __init__(self, initial_state: LifecycleState = LifecycleState.INIT):
        self._state = initial_state
        self._history: list[TransitionRecord] = []
        self._callbacks: list[TransitionCallback] = []
        self._state_entered_at: dict[LifecycleState, datetime] = {
            initial_state: datetime.utcnow()
        }

    @property
    def state(self) -> LifecycleState:
        """Get current state."""
        return self._state

    @property
    def history(self) -> list[TransitionRecord]:
        """Get transition history."""
        return list(self._history)

    def is_healthy(self) -> bool:
        """Check if model is in a healthy state."""
        return self._state in {
            LifecycleState.READY,
            LifecycleState.SERVING,
        }

    def can_serve(self) -> bool:
        """Check if model can serve requests."""
        return self._state == LifecycleState.SERVING

    def is_ready(self) -> bool:
        """Check if model is ready (passed warming)."""
        return self._state in {
            LifecycleState.READY,
            LifecycleState.SERVING,
        }

    def can_transition(self, event: LifecycleEvent) -> bool:
        """Check if a transition is valid from current state."""
        valid_transitions = TRANSITIONS.get(self._state, {})
        return event in valid_transitions

    def get_valid_events(self) -> list[LifecycleEvent]:
        """Get list of valid events from current state."""
        return list(TRANSITIONS.get(self._state, {}).keys())

    async def transition(
        self,
        event: LifecycleEvent,
        metadata: dict[str, Any] | None = None,
    ) -> LifecycleState:
        """
        Attempt a state transition.

        Args:
            event: The event triggering the transition
            metadata: Optional metadata about the transition

        Returns:
            The new state after transition

        Raises:
            InvalidTransitionError: If transition is not valid
        """
        valid_transitions = TRANSITIONS.get(self._state, {})
        if event not in valid_transitions:
            raise InvalidTransitionError(
                self._state,
                event,
                f"Valid events: {list(valid_transitions.keys())}",
            )

        old_state = self._state
        new_state = valid_transitions[event]

        # Record transition
        record = TransitionRecord(
            from_state=old_state,
            to_state=new_state,
            event=event,
            metadata=metadata or {},
        )
        self._history.append(record)

        # Update state
        self._state = new_state
        self._state_entered_at[new_state] = datetime.utcnow()

        # Invoke callbacks
        for callback in self._callbacks:
            await callback(old_state, new_state, event)

        return new_state

    def add_callback(self, callback: TransitionCallback) -> None:
        """Add a callback for state transitions."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: TransitionCallback) -> bool:
        """Remove a callback. Returns True if removed."""
        try:
            self._callbacks.remove(callback)
            return True
        except ValueError:
            return False

    def time_in_state(self, state: LifecycleState | None = None) -> float:
        """Get time spent in a state in seconds."""
        target_state = state or self._state
        if target_state not in self._state_entered_at:
            return 0.0

        entered = self._state_entered_at[target_state]
        return (datetime.utcnow() - entered).total_seconds()

    def get_state_duration(self, state: LifecycleState) -> float | None:
        """
        Get total time spent in a state.

        For completed states, returns the total time.
        For current state, returns time so far.
        """
        total = 0.0

        for i, record in enumerate(self._history):
            if record.from_state == state:
                # Find the end of this state period
                next_time = (
                    self._history[i + 1].timestamp
                    if i + 1 < len(self._history)
                    else datetime.utcnow()
                )
                total += (next_time - record.timestamp).total_seconds()

        return total if total > 0 else None

    async def reset(self) -> None:
        """Reset to initial state."""
        self._state = LifecycleState.INIT
        self._history.clear()
        self._state_entered_at = {LifecycleState.INIT: datetime.utcnow()}

    def to_dict(self) -> dict[str, Any]:
        """Serialize state machine to dictionary."""
        return {
            "current_state": self._state.name,
            "is_healthy": self.is_healthy(),
            "can_serve": self.can_serve(),
            "valid_events": [e.name for e in self.get_valid_events()],
            "history": [
                {
                    "from": r.from_state.name,
                    "to": r.to_state.name,
                    "event": r.event.name,
                    "timestamp": r.timestamp.isoformat(),
                    "metadata": r.metadata,
                }
                for r in self._history[-10:]  # Last 10 transitions
            ],
        }


class LifecycleManager:
    """
    High-level lifecycle manager with warming support.

    Orchestrates the lifecycle of a model including:
    - Loading the model
    - Running warming tests (golden set)
    - Transitioning to ready/serving states
    - Graceful shutdown with draining
    """

    def __init__(
        self,
        state_machine: LifecycleStateMachine | None = None,
        warming_timeout_seconds: float = 300.0,
    ):
        self._state_machine = state_machine or LifecycleStateMachine()
        self._warming_timeout = warming_timeout_seconds
        self._warming_passed = False
        self._warming_results: dict[str, Any] = {}

    @property
    def state_machine(self) -> LifecycleStateMachine:
        return self._state_machine

    @property
    def state(self) -> LifecycleState:
        return self._state_machine.state

    @property
    def warming_passed(self) -> bool:
        return self._warming_passed

    @property
    def warming_results(self) -> dict[str, Any]:
        return dict(self._warming_results)

    async def start_loading(self) -> bool:
        """Begin loading the model."""
        try:
            await self._state_machine.transition(LifecycleEvent.LOAD)
            return True
        except InvalidTransitionError:
            return False

    async def complete_loading(self) -> bool:
        """Mark loading as complete, transition to warming."""
        try:
            await self._state_machine.transition(LifecycleEvent.LOAD_COMPLETE)
            return True
        except InvalidTransitionError:
            return False

    async def complete_warming(
        self,
        passed: bool,
        results: dict[str, Any] | None = None,
    ) -> bool:
        """
        Complete the warming phase.

        Args:
            passed: True if warming tests passed
            results: Optional warming test results

        Returns:
            True if state transition succeeded
        """
        self._warming_passed = passed
        self._warming_results = results or {}

        event = LifecycleEvent.WARM_COMPLETE if passed else LifecycleEvent.WARM_FAILED

        try:
            await self._state_machine.transition(
                event,
                metadata={"warming_passed": passed, "results": results},
            )
            return True
        except InvalidTransitionError:
            return False

    async def start_serving(self) -> bool:
        """Start serving requests."""
        try:
            await self._state_machine.transition(LifecycleEvent.START_SERVING)
            return True
        except InvalidTransitionError:
            return False

    async def drain(self) -> bool:
        """Begin draining (stop accepting new requests)."""
        try:
            await self._state_machine.transition(LifecycleEvent.DRAIN)
            return True
        except InvalidTransitionError:
            return False

    async def complete_drain(self) -> bool:
        """Complete draining and stop."""
        try:
            await self._state_machine.transition(LifecycleEvent.DRAIN_COMPLETE)
            return True
        except InvalidTransitionError:
            return False

    async def stop(self) -> bool:
        """Stop immediately."""
        try:
            await self._state_machine.transition(LifecycleEvent.STOP)
            return True
        except InvalidTransitionError:
            return False

    async def fail(self, reason: str = "") -> bool:
        """Mark as failed."""
        try:
            await self._state_machine.transition(
                LifecycleEvent.FAIL,
                metadata={"reason": reason},
            )
            return True
        except InvalidTransitionError:
            return False

    async def recover(self) -> bool:
        """Attempt to recover from failed state."""
        try:
            await self._state_machine.transition(LifecycleEvent.RECOVER)
            return True
        except InvalidTransitionError:
            return False
