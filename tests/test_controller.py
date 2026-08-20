"""Tests for the event-driven Runtime Auto-Off controller."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.runtime_auto_off.controller import RuntimeAutoOffController
from custom_components.runtime_auto_off.models import (
    RuleConfig,
    ShutdownKind,
    Status,
    TriggerPolicy,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

AREA_ID = "test_room"
LIGHT = "light.room"
SWITCH = "switch.room"
SHABBAT = "binary_sensor.shabbat_or_holiday"


@dataclass(slots=True)
class TurnOffRecorder:
    hass: HomeAssistant
    calls: list[str] = field(default_factory=list)
    failures: set[str] = field(default_factory=set)
    ignored: set[str] = field(default_factory=set)

    async def async_handle(self, call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        assert isinstance(entity_id, str)
        self.calls.append(entity_id)
        if entity_id in self.failures:
            raise HomeAssistantError("simulated failure")
        if entity_id not in self.ignored:
            self.hass.states.async_set(entity_id, STATE_OFF)


type ControllerFactory = Callable[
    [RuleConfig, str | None], Awaitable[RuntimeAutoOffController]
]


@pytest.fixture
def turn_off_recorder(hass: HomeAssistant) -> TurnOffRecorder:
    recorder = TurnOffRecorder(hass)
    for domain in ("light", "switch"):
        hass.services.async_register(domain, SERVICE_TURN_OFF, recorder.async_handle)
    return recorder


@pytest.fixture
async def controller_factory(
    hass: HomeAssistant,
) -> AsyncIterator[ControllerFactory]:
    controllers: list[RuntimeAutoOffController] = []

    async def factory(
        config: RuleConfig, entry_id: str | None = None
    ) -> RuntimeAutoOffController:
        areas = ar.async_get(hass)
        if areas.async_get_area(AREA_ID) is None:
            area = areas.async_create(AREA_ID)
            assert area.id == AREA_ID
        registry = er.async_get(hass)
        for entity_id in config.entities:
            entry = registry.async_get(entity_id)
            if entry is None:
                old_state = hass.states.get(entity_id)
                if old_state is not None:
                    hass.states.async_remove(entity_id)
                domain, object_id = split_entity_id(entity_id)
                entry = registry.async_get_or_create(
                    domain,
                    "test",
                    f"runtime-{entity_id}",
                    suggested_object_id=object_id,
                )
                assert entry.entity_id == entity_id
                if old_state is not None:
                    hass.states.async_set(
                        entity_id, old_state.state, dict(old_state.attributes)
                    )
            registry.async_update_entity(entity_id, area_id=config.area_id)
            if hass.states.get(entity_id) is None:
                hass.states.async_set(entity_id, STATE_OFF)

        controller = RuntimeAutoOffController(
            hass,
            entry_id or f"entry-{len(controllers) + 1}",
            config,
        )
        controllers.append(controller)
        await controller.async_setup()
        return controller

    yield factory

    for controller in reversed(controllers):
        await controller.async_unload()


def _config(
    *,
    delay: float = 600,
    retry_interval: float | None = None,
    trigger_policy: TriggerPolicy = TriggerPolicy.FIRST,
    entities: tuple[str, ...] = (LIGHT, SWITCH),
    shabbat_entity: str | None = None,
) -> RuleConfig:
    return RuleConfig(
        "Test room",
        AREA_ID,
        entities,
        delay,
        "test-rule",
        retry_interval,
        trigger_policy,
        shabbat_entity,
    )


async def test_shabbat_sensor_blocks_shutdown_until_special_day_ends(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    hass.states.async_set(SHABBAT, STATE_ON)
    hass.states.async_set(LIGHT, STATE_ON)
    controller = await controller_factory(
        _config(delay=0, entities=(LIGHT,), shabbat_entity=SHABBAT)
    )

    assert controller.status is Status.WAITING_CONDITION
    assert controller.deadline is None
    assert turn_off_recorder.calls == []

    hass.states.async_set(SHABBAT, STATE_OFF)
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT]
    assert hass.states[LIGHT].state == STATE_OFF


async def test_unavailable_shabbat_sensor_fails_closed(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    hass.states.async_set(SHABBAT, STATE_UNAVAILABLE)
    hass.states.async_set(LIGHT, STATE_ON)
    controller = await controller_factory(
        _config(delay=0, entities=(LIGHT,), shabbat_entity=SHABBAT)
    )

    assert controller.status is Status.SENSOR_UNAVAILABLE
    assert turn_off_recorder.calls == []


async def test_countdown_follows_continuous_active_transition(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    controller = await controller_factory(_config())

    hass.states.async_set(LIGHT, STATE_ON)
    active_state = hass.states.get(LIGHT)
    assert active_state is not None
    await hass.async_block_till_done()

    deadline = active_state.last_changed + timedelta(minutes=10)
    assert controller.status is Status.COUNTDOWN
    assert controller.trigger_entity == LIGHT
    assert controller.deadline == deadline

    hass.states.async_set(LIGHT, STATE_ON, {"brightness": 100})
    await hass.async_block_till_done()
    assert controller.deadline == deadline
    assert turn_off_recorder.calls == []

    hass.states.async_set(LIGHT, STATE_OFF)
    await hass.async_block_till_done()
    assert controller.status is Status.IDLE
    assert controller.deadline is None


async def test_first_due_entity_turns_every_active_selection_off(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    controller = await controller_factory(_config(delay=600))
    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    hass.states.async_set(SWITCH, STATE_ON)
    await hass.async_block_till_done()

    assert controller.deadline is not None
    async_fire_time_changed(hass, controller.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT, SWITCH]
    assert controller.last_execution is not None
    assert controller.last_execution.trigger_entity == LIGHT
    assert set(controller.last_execution.successful_entities) == {LIGHT, SWITCH}


async def test_already_off_selection_is_not_called(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    hass.states.async_set(LIGHT, STATE_ON)
    hass.states.async_set(SWITCH, STATE_OFF)
    controller = await controller_factory(_config(delay=0))

    assert turn_off_recorder.calls == [LIGHT]
    assert controller.last_execution is not None
    assert controller.last_execution.skipped_entities == {SWITCH: "already_off"}


async def test_failed_active_cycle_retries_after_configured_interval(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    controller = await controller_factory(
        _config(delay=2700, retry_interval=300, entities=(LIGHT,))
    )
    initial_cycles = controller.diagnostics["active_cycles"]
    assert len(initial_cycles) == 1
    original_started_at = initial_cycles[0]["started_at"]

    first_deadline = controller.deadline
    assert first_deadline is not None
    assert controller.next_shutdown_kind is ShutdownKind.INITIAL
    async_fire_time_changed(hass, first_deadline + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT]
    assert controller.status is Status.COUNTDOWN
    retry_deadline = controller.deadline
    assert retry_deadline is not None
    assert controller.next_shutdown_kind is ShutdownKind.RETRY
    assert retry_deadline >= first_deadline + timedelta(minutes=5)
    assert retry_deadline <= first_deadline + timedelta(minutes=5, seconds=2)
    assert controller.last_execution is not None
    assert controller.last_execution.failed_entities == {LIGHT: "HomeAssistantError"}
    active_cycles = controller.diagnostics["active_cycles"]
    assert len(active_cycles) == 1
    assert active_cycles[0]["started_at"] == original_started_at
    assert active_cycles[0]["retry_at"] == retry_deadline.isoformat()

    hass.states.async_set(LIGHT, STATE_ON, {"brightness": 50})
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT]
    assert controller.deadline == retry_deadline

    turn_off_recorder.failures.remove(LIGHT)
    assert controller.deadline is not None
    async_fire_time_changed(hass, controller.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT, LIGHT]
    assert hass.states.get(LIGHT) is not None
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert controller.deadline is None


async def test_partial_failure_retries_only_the_entity_still_active(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(SWITCH)
    hass.states.async_set(LIGHT, STATE_ON)
    hass.states.async_set(SWITCH, STATE_ON)
    controller = await controller_factory(_config(delay=60))

    assert controller.deadline is not None
    async_fire_time_changed(hass, controller.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT, SWITCH]
    assert hass.states.get(LIGHT) is not None
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SWITCH) is not None
    assert hass.states.get(SWITCH).state == STATE_ON
    retry_deadline = controller.deadline
    assert retry_deadline is not None

    turn_off_recorder.failures.remove(SWITCH)
    async_fire_time_changed(hass, retry_deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT, SWITCH, SWITCH]
    assert hass.states.get(SWITCH) is not None
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert controller.deadline is None


async def test_unconfirmed_turn_off_is_failed_and_retried(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.ignored.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    controller = await controller_factory(_config(delay=60, entities=(LIGHT,)))

    assert controller.deadline is not None
    async_fire_time_changed(hass, controller.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT]
    assert controller.last_execution is not None
    assert controller.last_execution.failed_entities == {
        LIGHT: "turn_off_not_confirmed"
    }
    retry_deadline = controller.deadline
    assert retry_deadline is not None

    turn_off_recorder.ignored.remove(LIGHT)
    async_fire_time_changed(hass, retry_deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT, LIGHT]
    assert hass.states.get(LIGHT) is not None
    assert hass.states.get(LIGHT).state == STATE_OFF
    assert controller.deadline is None


async def test_handled_cycle_does_not_replay_after_restart(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    config = _config(delay=0, entities=(LIGHT,))
    first = await controller_factory(config, "restart-entry")
    assert turn_off_recorder.calls == [LIGHT]
    await first.async_unload()

    restarted = await controller_factory(config, "restart-entry")
    assert restarted.status is Status.COMPLETED
    assert restarted.deadline is None
    assert turn_off_recorder.calls == [LIGHT]


async def test_retry_deadline_survives_restart(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    config = _config(delay=600, entities=(LIGHT,))
    first = await controller_factory(config, "retry-restart-entry")
    assert first.deadline is not None
    async_fire_time_changed(hass, first.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()
    retry_deadline = first.deadline
    assert retry_deadline is not None
    assert turn_off_recorder.calls == [LIGHT]
    await first.async_unload()

    restarted = await controller_factory(config, "retry-restart-entry")
    assert restarted.status is Status.COUNTDOWN
    assert restarted.deadline == retry_deadline
    turn_off_recorder.failures.remove(LIGHT)
    async_fire_time_changed(hass, retry_deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == [LIGHT, LIGHT]
    assert hass.states.get(LIGHT) is not None
    assert hass.states.get(LIGHT).state == STATE_OFF


async def test_last_policy_tracks_most_recently_activated_entity(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
) -> None:
    controller = await controller_factory(
        _config(delay=600, trigger_policy=TriggerPolicy.LAST)
    )
    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    light_deadline = controller.deadline
    assert light_deadline is not None

    hass.states.async_set(SWITCH, STATE_ON)
    switch_state = hass.states.get(SWITCH)
    assert switch_state is not None
    await hass.async_block_till_done()

    assert controller.trigger_entity == SWITCH
    assert controller.deadline == switch_state.last_changed + timedelta(minutes=10)
    assert controller.deadline >= light_deadline

    hass.states.async_set(SWITCH, STATE_OFF)
    await hass.async_block_till_done()
    assert controller.trigger_entity == LIGHT
    assert controller.deadline == light_deadline


async def test_unavailable_and_restart_preserve_continuous_runtime(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    config = _config(delay=600, retry_interval=60, entities=(LIGHT,))
    first = await controller_factory(config, "unavailable-restart-entry")
    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    original_deadline = first.deadline
    original_started_at = first.active_since[LIGHT]
    assert original_deadline is not None

    hass.states.async_set(LIGHT, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert first.active_since[LIGHT] == original_started_at
    assert first.deadline == original_deadline
    assert first.unavailable_entities == {LIGHT: STATE_UNAVAILABLE}
    await first.async_unload()

    restarted = await controller_factory(config, "unavailable-restart-entry")
    assert restarted.active_since[LIGHT] == original_started_at
    assert restarted.deadline == original_deadline
    assert restarted.unavailable_entities == {LIGHT: STATE_UNAVAILABLE}

    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    assert restarted.active_since[LIGHT] == original_started_at
    assert restarted.deadline == original_deadline
    async_fire_time_changed(hass, original_deadline + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT]


async def test_options_reload_recalculates_existing_retry_deadline(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    first = await controller_factory(
        _config(delay=0, retry_interval=2700, entities=(LIGHT,)),
        "retry-options-entry",
    )
    old_retry_deadline = first.deadline
    assert old_retry_deadline is not None
    await first.async_unload()

    reloaded = await controller_factory(
        _config(delay=0, retry_interval=180, entities=(LIGHT,)),
        "retry-options-entry",
    )
    assert reloaded.next_shutdown_kind is ShutdownKind.RETRY
    assert reloaded.deadline == old_retry_deadline - timedelta(minutes=42)


async def test_moved_entity_is_never_called(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    controller = await controller_factory(_config(delay=600, entities=(LIGHT,)))
    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    other = ar.async_get(hass).async_create("Other room")
    er.async_get(hass).async_update_entity(LIGHT, area_id=other.id)

    assert controller.deadline is not None
    async_fire_time_changed(hass, controller.deadline + timedelta(seconds=1))
    await hass.async_block_till_done()

    assert turn_off_recorder.calls == []
    assert controller.status is Status.SENSOR_UNAVAILABLE
