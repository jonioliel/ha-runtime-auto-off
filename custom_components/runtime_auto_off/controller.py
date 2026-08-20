"""Event-driven controller for SmplWise Runtime Auto-Off."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
    split_entity_id,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DATA,
    ATTR_ENTRY_ID,
    ATTR_EVENT_TYPE,
    ATTR_OCCURRED_AT,
    ATTR_RULE_ID,
    DEFAULT_ENABLED,
    EVENT_ACTIVITY,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .helpers import effective_area_id
from .models import (
    ActivityEvent,
    ActivityEventType,
    LastExecution,
    RuleConfig,
    RuntimeCycle,
    ShutdownKind,
    Status,
    TriggerPolicy,
)

_LOGGER = logging.getLogger(__name__)
_TARGET_SERVICE_TIMEOUT_SECONDS = 30.0

StateListener = Callable[[], None]
ActivityListener = Callable[[ActivityEvent], None]


@dataclass(frozen=True, slots=True)
class _ExecutionPlan:
    """A durably claimed runtime-limit execution."""

    trigger_key: str
    trigger_entity: str
    trigger_started_at: datetime
    claimed_at: datetime
    is_retry: bool
    target_entities: tuple[str, ...]


class RuntimeAutoOffController:
    """Track continuous active time and retry shutdowns that leave entities on."""

    def __init__(self, hass: HomeAssistant, entry_id: str, config: RuleConfig) -> None:
        if not config.entities:
            raise ValueError("At least one entity is required")

        self.hass = hass
        self.entry_id = entry_id
        self.config = config if config.rule_id else replace(config, rule_id=entry_id)

        registry = er.async_get(hass)
        self._registry_id_by_entity: dict[str, str | None] = {}
        self._stable_key_by_entity: dict[str, str] = {}
        for entity_id in self.config.entities:
            entry = registry.async_get(entity_id)
            registry_id = entry.id if entry is not None else None
            self._registry_id_by_entity[entity_id] = registry_id
            self._stable_key_by_entity[entity_id] = (
                registry_id if registry_id is not None else f"entity:{entity_id}"
            )

        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}.{entry_id}",
            private=True,
            atomic_writes=True,
        )
        self._lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()
        self._execution_tasks: set[asyncio.Task[Any]] = set()
        self._execution_idle = asyncio.Event()
        self._execution_idle.set()

        self._enabled = DEFAULT_ENABLED
        self._action_inhibited = not DEFAULT_ENABLED
        self._status = Status.INITIALIZING
        self._cycles: dict[str, RuntimeCycle] = {}
        self._unavailable_entities: dict[str, str] = {}
        self._next_deadline: datetime | None = None
        self._next_shutdown_kind: ShutdownKind | None = None
        self._trigger_entity: str | None = None
        self._last_execution: LastExecution | None = None
        self._last_activity: ActivityEvent | None = None
        self._last_saved_payload: dict[str, Any] | None = None
        self._stored_retry_interval_seconds: float | None = None

        self._state_listeners: set[StateListener] = set()
        self._activity_listeners: set[ActivityListener] = set()
        self._unsub_state: CALLBACK_TYPE | None = None
        self._unsub_deadline: CALLBACK_TYPE | None = None
        self._timer_generation = 0
        self._setup_complete = False
        self._unloaded = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> Status:
        return self._status

    @property
    def deadline(self) -> datetime | None:
        return self._next_deadline

    @property
    def trigger_entity(self) -> str | None:
        return self._trigger_entity

    @property
    def trigger_started_at(self) -> datetime | None:
        """Return when the currently triggering entity became active."""
        for cycle in self._cycles.values():
            if cycle.entity_id == self._trigger_entity:
                return cycle.started_at
        return None

    @property
    def next_shutdown_kind(self) -> ShutdownKind | None:
        return self._next_shutdown_kind

    @property
    def active_since(self) -> dict[str, datetime]:
        """Return the preserved active start time for every tracked entity."""
        return {
            cycle.entity_id: cycle.started_at
            for cycle in sorted(self._cycles.values(), key=lambda item: item.entity_id)
        }

    @property
    def unavailable_entities(self) -> dict[str, str]:
        return dict(self._unavailable_entities)

    @property
    def any_active(self) -> bool:
        return bool(self._cycles)

    @property
    def last_execution(self) -> LastExecution | None:
        return self._last_execution

    @property
    def last_activity(self) -> ActivityEvent | None:
        return self._last_activity

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "rule_id": self.config.rule_id,
            "config": self.config.as_dict(),
            "enabled": self.enabled,
            "status": self.status.value,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "next_shutdown_kind": (
                self.next_shutdown_kind.value if self.next_shutdown_kind else None
            ),
            "trigger_entity": self.trigger_entity,
            "shabbat_sensor_state": (
                self.hass.states.get(self.config.shabbat_entity).state
                if self.config.shabbat_entity
                and self.hass.states.get(self.config.shabbat_entity) is not None
                else None
            ),
            "active_cycles": [
                cycle.as_dict()
                for cycle in sorted(
                    self._cycles.values(), key=lambda item: item.entity_id
                )
            ],
            "unavailable_entities": dict(self._unavailable_entities),
            "last_execution": (
                self.last_execution.as_dict() if self.last_execution else None
            ),
            "last_activity": (
                self.last_activity.as_dict() if self.last_activity else None
            ),
        }

    @callback
    def async_add_listener(self, listener: StateListener) -> CALLBACK_TYPE:
        self._state_listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._state_listeners.discard(listener)

        return remove_listener

    @callback
    def async_add_activity_listener(self, listener: ActivityListener) -> CALLBACK_TYPE:
        self._activity_listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._activity_listeners.discard(listener)

        return remove_listener

    async def async_setup(self) -> None:
        """Restore durable cycles and reconcile current entity states."""
        try:
            stored = await self._store.async_load()
            self._subscribe_state_changes()
            async with self._lock:
                self._unloaded = False
                self._restore_locked(stored)
                self._sync_cycles_locked()
                now = dt_util.utcnow()
                self._apply_retry_interval_change_locked(now)
                self._rearm_interrupted_cycles_locked(now)
                plan, activity = self._reconcile_locked(now)
                self._setup_complete = True
                await self._async_save_locked(force=True)
                self._action_inhibited = not self._enabled
            self._notify_state_listeners()
            if activity is not None:
                self._publish_activity(activity)
            if plan is not None:
                await self._async_execute(plan)
        except BaseException:
            self._rollback_failed_setup()
            raise

    async def async_stop(self) -> None:
        """Stop new work and wait for every running service call."""
        self._unsubscribe_state_changes()
        if self._unloaded:
            await self._execution_idle.wait()
            return
        self._unloaded = True
        self._action_inhibited = True
        async with self._lock:
            self._cancel_deadline_locked()
            try:
                await self._async_save_locked(force=True)
            except Exception:
                _LOGGER.warning(
                    "Could not persist stopped Runtime Auto-Off rule %s",
                    self.config.rule_id,
                    exc_info=True,
                )
        await self._execution_idle.wait()

    async def async_resume(self) -> None:
        """Resume after a rejected platform unload."""
        if not self._setup_complete or not self._unloaded:
            return
        self._subscribe_state_changes()
        try:
            async with self._lock:
                self._unloaded = False
                self._action_inhibited = not self._enabled
                self._sync_cycles_locked()
                plan, activity = self._reconcile_locked(dt_util.utcnow())
                await self._async_save_locked()
            self._notify_state_listeners()
            if activity is not None:
                self._publish_activity(activity)
            if plan is not None:
                await self._async_execute(plan)
        except BaseException:
            self._unsubscribe_state_changes()
            self._cancel_deadline_locked()
            self._unloaded = True
            self._action_inhibited = True
            raise

    async def async_unload(self) -> None:
        await self.async_stop()
        self._setup_complete = False
        self._state_listeners.clear()
        self._activity_listeners.clear()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Persistently enable or pause this rule."""
        if not enabled:
            self._action_inhibited = True
        async with self._lock:
            if self._unloaded or enabled == self._enabled:
                return
            self._enabled = enabled
            if enabled:
                self._action_inhibited = False
                self._sync_cycles_locked()
                plan, activity = self._reconcile_locked(dt_util.utcnow())
            else:
                self._cancel_deadline_locked()
                self._status = Status.DISABLED
                plan = None
                activity = self._new_activity_locked(
                    ActivityEventType.CANCELLED, {"reason": "controller_disabled"}
                )
            await self._async_save_locked()
        self._notify_state_listeners()
        if activity is not None:
            self._publish_activity(activity)
        if plan is not None:
            await self._async_execute(plan)

    async def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Reconcile selected entity state changes."""
        async with self._lock:
            if not self._setup_complete or self._unloaded:
                return
            previous_deadline = self._next_deadline
            self._sync_cycles_locked(event)
            plan, activity = self._reconcile_locked(dt_util.utcnow())
            if (
                activity is None
                and previous_deadline is not None
                and self._next_deadline is None
                and plan is None
            ):
                activity = self._new_activity_locked(
                    ActivityEventType.CANCELLED,
                    {"reason": "no_pending_active_cycle"},
                )
            await self._async_save_locked()
        self._notify_state_listeners()
        if activity is not None:
            self._publish_activity(activity)
        if plan is not None:
            await self._async_execute(plan)

    async def _async_deadline_reached(self, generation: int, _now: datetime) -> None:
        """Handle the earliest continuous-runtime deadline."""
        async with self._lock:
            if self._unloaded or generation != self._timer_generation:
                return
            self._unsub_deadline = None
            self._next_deadline = None
            self._sync_cycles_locked()
            plan, activity = self._reconcile_locked(dt_util.as_utc(_now))
            await self._async_save_locked()
        self._notify_state_listeners()
        if activity is not None:
            self._publish_activity(activity)
        if plan is not None:
            await self._async_execute(plan)

    def _reconcile_locked(
        self, now: datetime
    ) -> tuple[_ExecutionPlan | None, ActivityEvent | None]:
        """Schedule the earliest cycle or durably claim a due batch."""
        if not self._enabled:
            self._cancel_deadline_locked()
            self._next_shutdown_kind = None
            self._status = Status.DISABLED
            return None, None

        if not self._cycles:
            self._cancel_deadline_locked()
            self._next_shutdown_kind = None
            self._trigger_entity = None
            self._status = (
                Status.SENSOR_UNAVAILABLE
                if len(self._unavailable_entities) == len(self.config.entities)
                else Status.IDLE
            )
            return None, None

        shabbat_block = self._shabbat_block_reason()
        if shabbat_block is not None:
            if shabbat_block == "sensor_unavailable":
                self._cancel_deadline_locked()
                self._trigger_entity = None
                self._status = Status.SENSOR_UNAVAILABLE
                return None, None
            self._cancel_deadline_locked()
            self._trigger_entity = None
            self._status = Status.WAITING_CONDITION
            return None, None

        pending = [cycle for cycle in self._cycles.values() if not cycle.handled]
        if not pending:
            self._cancel_deadline_locked()
            self._next_shutdown_kind = None
            self._trigger_entity = None
            self._status = Status.COMPLETED
            return None, None

        retry_pending = [cycle for cycle in pending if cycle.retry_at is not None]
        if retry_pending:
            trigger = min(
                retry_pending,
                key=lambda cycle: (
                    cycle.deadline(self.config.delay_seconds),
                    cycle.stable_key,
                ),
            )
        elif self.config.trigger_policy is TriggerPolicy.LAST:
            trigger = max(
                pending,
                key=lambda cycle: (
                    cycle.deadline(self.config.delay_seconds),
                    cycle.stable_key,
                ),
            )
        else:
            trigger = min(
                pending,
                key=lambda cycle: (
                    cycle.deadline(self.config.delay_seconds),
                    cycle.stable_key,
                ),
            )
        deadline = trigger.deadline(self.config.delay_seconds)
        is_retry = trigger.retry_at is not None
        self._trigger_entity = trigger.entity_id
        if now < deadline:
            changed = self._next_deadline != deadline
            self._schedule_deadline_locked(deadline)
            self._next_shutdown_kind = (
                ShutdownKind.RETRY if is_retry else ShutdownKind.INITIAL
            )
            self._status = Status.COUNTDOWN
            activity = (
                self._new_activity_locked(
                    ActivityEventType.SCHEDULED,
                    {
                        "trigger_entity": trigger.entity_id,
                        "started_at": trigger.started_at.isoformat(),
                        "deadline": deadline.isoformat(),
                        "is_retry": is_retry,
                    },
                )
                if changed
                else None
            )
            return None, activity

        self._cancel_deadline_locked()
        self._next_shutdown_kind = None
        self._trigger_entity = trigger.entity_id
        # Claim every entity that is currently active. This prevents a second
        # overdue entity from creating a parallel or repeating execution.
        self._cycles = {
            key: replace(cycle, handled=True) for key, cycle in self._cycles.items()
        }
        self._status = Status.EXECUTING
        return (
            _ExecutionPlan(
                trigger_key=trigger.stable_key,
                trigger_entity=trigger.entity_id,
                trigger_started_at=trigger.started_at,
                claimed_at=now,
                is_retry=is_retry,
                target_entities=self.config.entities,
            ),
            None,
        )

    async def _async_execute(self, plan: _ExecutionPlan) -> None:
        """Serialize an automatic shutdown and track it for unload."""
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Runtime execution must run in an asyncio task")
        self._execution_tasks.add(task)
        self._execution_idle.clear()
        try:
            async with self._execution_lock:
                await self._async_execute_serialized(plan)
        finally:
            self._execution_tasks.discard(task)
            if not self._execution_tasks:
                self._execution_idle.set()

    async def _async_execute_serialized(self, plan: _ExecutionPlan) -> None:
        """Turn each selected active entity off independently."""
        if self._shabbat_block_reason() is not None:
            async with self._lock:
                self._cycles = {
                    key: replace(cycle, handled=False)
                    for key, cycle in self._cycles.items()
                }
                self._reconcile_locked(dt_util.utcnow())
                await self._async_save_locked()
            self._notify_state_listeners()
            return

        successful: list[str] = []
        skipped: dict[str, str] = {}
        failed: dict[str, str] = {}

        for entity_id in plan.target_entities:
            if shabbat_block := self._shabbat_block_reason():
                skipped[entity_id] = shabbat_block
                continue
            if self._unloaded or self._action_inhibited:
                failed[entity_id] = "controller_stopped"
                continue
            error = self._target_runtime_error(entity_id)
            if error == "already_off":
                skipped[entity_id] = error
                continue
            if error is not None:
                failed[entity_id] = error
                continue
            domain = split_entity_id(entity_id)[0]
            try:
                async with asyncio.timeout(_TARGET_SERVICE_TIMEOUT_SECONDS):
                    await self.hass.services.async_call(
                        domain,
                        SERVICE_TURN_OFF,
                        {ATTR_ENTITY_ID: entity_id},
                        blocking=True,
                    )
            except TimeoutError:
                failed[entity_id] = "service_timeout"
            except Exception as err:
                failed[entity_id] = type(err).__name__
                _LOGGER.warning(
                    "Could not turn off %s for runtime rule %s",
                    entity_id,
                    self.config.rule_id,
                    exc_info=True,
                )
            else:
                post_error = self._target_runtime_error(entity_id)
                if post_error == "already_off":
                    successful.append(entity_id)
                elif post_error is None:
                    failed[entity_id] = "turn_off_not_confirmed"
                else:
                    failed[entity_id] = f"post_turn_off_{post_error}"

        occurred_at = dt_util.utcnow()
        retry_base = max(occurred_at, plan.claimed_at)
        execution = LastExecution(
            trigger_entity=plan.trigger_entity,
            occurred_at=occurred_at,
            successful_entities=tuple(successful),
            skipped_entities=skipped,
            failed_entities=failed,
        )
        followup_plan: _ExecutionPlan | None = None
        followup_activity: ActivityEvent | None = None
        async with self._lock:
            self._sync_cycles_locked()
            self._rearm_interrupted_cycles_locked(retry_base)
            self._last_execution = execution
            self._status = Status.ERROR if failed else Status.COMPLETED
            event_type = (
                ActivityEventType.FAILED
                if failed
                else (
                    ActivityEventType.EXECUTED
                    if successful
                    else ActivityEventType.NO_ACTION
                )
            )
            execution_activity = self._new_activity_locked(
                event_type,
                {
                    "trigger_entity": plan.trigger_entity,
                    "trigger_started_at": plan.trigger_started_at.isoformat(),
                    "is_retry": plan.is_retry,
                    "successful_entities": list(successful),
                    "skipped_entities": dict(skipped),
                    "failed_entities": dict(failed),
                },
            )
            if (
                self._cycles
                and self.config.retry_interval_seconds > 0
                and not self._unloaded
            ):
                followup_plan, followup_activity = self._reconcile_locked(retry_base)
            try:
                await self._async_save_locked(force=True)
            except Exception:
                _LOGGER.warning(
                    "Could not persist execution for runtime rule %s",
                    self.config.rule_id,
                    exc_info=True,
                )
        self._notify_state_listeners()
        self._publish_activity(execution_activity)
        if followup_activity is not None:
            self._publish_activity(followup_activity)
        if followup_plan is not None:
            await self._async_execute_serialized(followup_plan)

    def _apply_retry_interval_change_locked(self, now: datetime) -> bool:
        """Recalculate persisted retry deadlines after an options change."""
        current_interval = float(self.config.retry_interval_seconds or 0)
        stored_interval = self._stored_retry_interval_seconds
        self._stored_retry_interval_seconds = current_interval
        if stored_interval is not None and math.isclose(
            stored_interval, current_interval, rel_tol=0, abs_tol=1e-6
        ):
            return False

        changed = False
        updated: dict[str, RuntimeCycle] = {}
        for key, cycle in self._cycles.items():
            if cycle.retry_at is not None and not cycle.handled:
                if stored_interval is not None and stored_interval > 0:
                    attempted_at = cycle.retry_at - timedelta(seconds=stored_interval)
                elif self._last_execution is not None:
                    attempted_at = self._last_execution.occurred_at
                else:
                    attempted_at = now
                cycle = replace(
                    cycle,
                    retry_at=attempted_at + timedelta(seconds=current_interval),
                )
                changed = True
            updated[key] = cycle
        self._cycles = updated
        return changed

    def _rearm_interrupted_cycles_locked(self, now: datetime) -> bool:
        """Schedule another check for active cycles claimed by an earlier attempt."""
        if self.config.retry_interval_seconds <= 0:
            return False
        retry_at = now + timedelta(seconds=self.config.retry_interval_seconds)
        rearmed = False
        updated: dict[str, RuntimeCycle] = {}
        for key, cycle in self._cycles.items():
            if cycle.handled:
                cycle = replace(cycle, handled=False, retry_at=retry_at)
                rearmed = True
            updated[key] = cycle
        self._cycles = updated
        return rearmed

    def _sync_cycles_locked(
        self, event: Event[EventStateChangedData] | None = None
    ) -> None:
        """Match persisted cycles to current selected entity states."""
        now = dt_util.utcnow()
        event_entity = event.data["entity_id"] if event is not None else None
        event_state = event.data["new_state"] if event is not None else None
        configured_keys = set(self._stable_key_by_entity.values())
        self._cycles = {
            key: cycle for key, cycle in self._cycles.items() if key in configured_keys
        }
        unavailable: dict[str, str] = {}

        for entity_id in self.config.entities:
            key = self._stable_key_by_entity[entity_id]
            identity_error = self._identity_or_area_error(entity_id)
            # Process queued transitions in event order. Looking only at the
            # latest state could miss a rapid off-to-on cycle and incorrectly
            # keep the previous cycle marked as handled.
            state = (
                event_state
                if entity_id == event_entity
                else self.hass.states.get(entity_id)
            )
            if identity_error is not None:
                unavailable[entity_id] = identity_error
                self._cycles.pop(key, None)
                continue
            if state is None:
                unavailable[entity_id] = "missing_state"
                if key in self._cycles:
                    cycle = self._cycles[key]
                    if cycle.entity_id != entity_id:
                        self._cycles[key] = replace(cycle, entity_id=entity_id)
                continue
            if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                unavailable[entity_id] = state.state
                if key in self._cycles:
                    cycle = self._cycles[key]
                    if cycle.entity_id != entity_id:
                        self._cycles[key] = replace(cycle, entity_id=entity_id)
                continue
            if state.state == STATE_OFF:
                self._cycles.pop(key, None)
                continue
            if key in self._cycles:
                cycle = self._cycles[key]
                if cycle.entity_id != entity_id:
                    self._cycles[key] = replace(cycle, entity_id=entity_id)
                continue
            changed_at = min(dt_util.as_utc(state.last_changed), now)
            self._cycles[key] = RuntimeCycle(key, entity_id, changed_at)

        self._unavailable_entities = unavailable

    def _identity_or_area_error(self, entity_id: str) -> str | None:
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        expected = self._registry_id_by_entity.get(entity_id)
        if expected is not None:
            if entry is None:
                return "missing_registry_entry"
            if entry.id != expected:
                return "entity_identity_changed"
        elif entry is not None:
            return "entity_identity_changed"
        if entry is not None:
            if entry.disabled:
                return "disabled"
            if effective_area_id(self.hass, entry) != self.config.area_id:
                return "out_of_area"
        return None

    def _target_runtime_error(self, entity_id: str) -> str | None:
        if error := self._identity_or_area_error(entity_id):
            return error
        domain = split_entity_id(entity_id)[0]
        if not self.hass.services.has_service(domain, SERVICE_TURN_OFF):
            return "unsupported_service"
        state = self.hass.states.get(entity_id)
        if state is None:
            return "missing_state"
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return state.state
        if state.state == STATE_OFF:
            return "already_off"
        return None

    def _shabbat_block_reason(self) -> str | None:
        """Return why the optional combined Shabbat/holiday gate blocks actions."""
        if self.config.shabbat_entity is None:
            return None
        state = self.hass.states.get(self.config.shabbat_entity)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return "sensor_unavailable"
        if state.state == STATE_ON:
            return "shabbat_or_holiday"
        return None

    def _schedule_deadline_locked(self, deadline: datetime) -> None:
        if self._unsub_deadline is not None and self._next_deadline == deadline:
            return
        self._cancel_deadline_locked()
        self._timer_generation += 1
        generation = self._timer_generation
        self._next_deadline = deadline

        async def deadline_reached(now: datetime) -> None:
            await self._async_deadline_reached(generation, now)

        self._unsub_deadline = async_track_point_in_utc_time(
            self.hass, deadline_reached, deadline
        )

    def _cancel_deadline_locked(self) -> None:
        self._timer_generation += 1
        if self._unsub_deadline is not None:
            self._unsub_deadline()
            self._unsub_deadline = None
        self._next_deadline = None
        self._next_shutdown_kind = None

    @callback
    def _subscribe_state_changes(self) -> None:
        if self._unsub_state is None:
            tracked_entities = list(self.config.entities)
            if self.config.shabbat_entity is not None:
                tracked_entities.append(self.config.shabbat_entity)
            self._unsub_state = async_track_state_change_event(
                self.hass, tracked_entities, self._async_state_changed
            )

    @callback
    def _unsubscribe_state_changes(self) -> None:
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _rollback_failed_setup(self) -> None:
        self._unsubscribe_state_changes()
        self._cancel_deadline_locked()
        self._cycles.clear()
        self._setup_complete = False
        self._unloaded = True
        self._action_inhibited = True
        self._state_listeners.clear()
        self._activity_listeners.clear()

    def _restore_locked(self, stored: Mapping[str, Any] | None) -> None:
        if stored is None:
            return
        if isinstance(enabled := stored.get("enabled"), bool):
            self._enabled = enabled
        raw_retry_interval = stored.get("retry_interval_seconds")
        if (
            isinstance(raw_retry_interval, (int, float))
            and not isinstance(raw_retry_interval, bool)
            and math.isfinite(raw_retry_interval)
            and raw_retry_interval >= 0
        ):
            self._stored_retry_interval_seconds = float(raw_retry_interval)
        raw_cycles = stored.get("cycles")
        if isinstance(raw_cycles, list):
            for raw_cycle in raw_cycles:
                if not isinstance(raw_cycle, Mapping):
                    continue
                cycle = RuntimeCycle.from_dict(raw_cycle)
                if cycle is not None:
                    self._cycles[cycle.stable_key] = cycle
        raw_execution = stored.get("last_execution")
        if isinstance(raw_execution, Mapping):
            self._last_execution = LastExecution.from_dict(raw_execution)

    async def _async_save_locked(self, *, force: bool = False) -> None:
        payload = {
            "enabled": self._enabled,
            "retry_interval_seconds": self.config.retry_interval_seconds,
            "cycles": [
                cycle.as_dict()
                for cycle in sorted(
                    self._cycles.values(), key=lambda item: item.stable_key
                )
            ],
            "last_execution": (
                self._last_execution.as_dict() if self._last_execution else None
            ),
        }
        if not force and payload == self._last_saved_payload:
            return
        await self._store.async_save(payload)
        self._last_saved_payload = payload

    def _new_activity_locked(
        self, event_type: ActivityEventType, data: Mapping[str, Any]
    ) -> ActivityEvent:
        activity = ActivityEvent(event_type, dt_util.utcnow(), dict(data))
        self._last_activity = activity
        return activity

    @callback
    def _notify_state_listeners(self) -> None:
        for listener in tuple(self._state_listeners):
            try:
                listener()
            except Exception:
                _LOGGER.exception(
                    "Error in listener for Runtime Auto-Off rule %s",
                    self.config.rule_id,
                )

    @callback
    def _publish_activity(self, activity: ActivityEvent) -> None:
        for listener in tuple(self._activity_listeners):
            try:
                listener(activity)
            except Exception:
                _LOGGER.exception(
                    "Error in activity listener for Runtime Auto-Off rule %s",
                    self.config.rule_id,
                )
        self.hass.bus.async_fire(
            EVENT_ACTIVITY,
            {
                ATTR_ENTRY_ID: self.entry_id,
                ATTR_RULE_ID: self.config.rule_id,
                ATTR_EVENT_TYPE: activity.event_type.value,
                ATTR_OCCURRED_AT: activity.occurred_at.isoformat(),
                ATTR_DATA: dict(activity.data),
            },
        )
