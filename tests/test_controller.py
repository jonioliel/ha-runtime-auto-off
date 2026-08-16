"""Tests for the event-driven Runtime Auto-Off controller."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, STATE_OFF, STATE_ON
from homeassistant.core import split_entity_id
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from custom_components.runtime_auto_off.controller import RuntimeAutoOffController
from custom_components.runtime_auto_off.models import RuleConfig, Status

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

AREA_ID = "test_room"
LIGHT = "light.room"
SWITCH = "switch.room"


@dataclass(slots=True)
class TurnOffRecorder:
    hass: HomeAssistant
    calls: list[str] = field(default_factory=list)
    failures: set[str] = field(default_factory=set)

    async def async_handle(self, call: ServiceCall) -> None:
        entity_id = call.data[ATTR_ENTITY_ID]
        assert isinstance(entity_id, str)
        self.calls.append(entity_id)
        if entity_id in self.failures:
            raise HomeAssistantError("simulated failure")
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
    *, delay: float = 600, entities: tuple[str, ...] = (LIGHT, SWITCH)
) -> RuleConfig:
    return RuleConfig("Test room", AREA_ID, entities, delay, "test-rule")


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
    await controller._async_deadline_reached(
        controller._timer_generation,
        controller.deadline + timedelta(seconds=1),
    )
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


async def test_failed_active_cycle_does_not_repeat_until_off_then_on(
    hass: HomeAssistant,
    controller_factory: ControllerFactory,
    turn_off_recorder: TurnOffRecorder,
) -> None:
    turn_off_recorder.failures.add(LIGHT)
    hass.states.async_set(LIGHT, STATE_ON)
    controller = await controller_factory(_config(delay=0, entities=(LIGHT,)))

    assert turn_off_recorder.calls == [LIGHT]
    assert controller.status is Status.ERROR
    assert controller.deadline is None

    hass.states.async_set(LIGHT, STATE_ON, {"brightness": 50})
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT]
    assert controller.deadline is None

    hass.states.async_set(LIGHT, STATE_OFF)
    await hass.async_block_till_done()
    hass.states.async_set(LIGHT, STATE_ON)
    await hass.async_block_till_done()
    assert turn_off_recorder.calls == [LIGHT, LIGHT]


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
    await controller._async_deadline_reached(
        controller._timer_generation,
        controller.deadline + timedelta(seconds=1),
    )

    assert turn_off_recorder.calls == []
    assert controller.status is Status.SENSOR_UNAVAILABLE
