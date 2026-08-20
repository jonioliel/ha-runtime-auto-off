"""Config-flow tests for Runtime Auto-Off."""

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import SERVICE_TURN_OFF
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.runtime_auto_off.config_flow import (
    CONF_DELAY,
    CONF_RETRY_INTERVAL,
)
from custom_components.runtime_auto_off.const import (
    CONF_AREA_ID,
    CONF_DELAY_SECONDS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_RETRY_INTERVAL_SECONDS,
    CONF_RULE_ID,
    CONF_SHABBAT_ENTITY,
    CONF_TRIGGER_POLICY,
    DOMAIN,
)
from custom_components.runtime_auto_off.models import TriggerPolicy

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall


def _schema_default(result: dict[str, Any], key: str) -> Any:
    marker = next(
        marker
        for marker in result["data_schema"].schema
        if getattr(marker, "schema", marker) == key
    )
    return marker.default()


async def test_user_flow_is_area_scoped_and_persists_registry_ids(
    hass: HomeAssistant,
) -> None:
    async def async_turn_off(_call: ServiceCall) -> None:
        pass

    hass.services.async_register("light", SERVICE_TURN_OFF, async_turn_off)
    areas = ar.async_get(hass)
    room = areas.async_create("Room")
    other = areas.async_create("Other")
    registry = er.async_get(hass)
    room_light = registry.async_get_or_create(
        "light", "test", "room-light", suggested_object_id="room_light"
    )
    room_light = registry.async_update_entity(room_light.entity_id, area_id=room.id)
    other_light = registry.async_get_or_create(
        "light", "test", "other-light", suggested_object_id="other_light"
    )
    other_light = registry.async_update_entity(other_light.entity_id, area_id=other.id)
    shabbat = registry.async_get_or_create(
        "binary_sensor",
        "test",
        "shabbat-or-holiday",
        suggested_object_id="shabbat_or_holiday",
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "TV limit", CONF_AREA_ID: room.id},
    )
    assert result["step_id"] == "entities"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENTITIES: [other_light.id]}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ENTITIES: "entity_not_allowed"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_ENTITIES: [room_light.entity_id, room_light.id]},
    )
    assert result["step_id"] == "delay"
    assert _schema_default(result, CONF_DELAY) == {"hours": 1}
    assert _schema_default(result, CONF_RETRY_INTERVAL) == {"minutes": 5}
    assert _schema_default(result, CONF_TRIGGER_POLICY) == TriggerPolicy.FIRST.value

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DELAY: {"minutes": 45},
            CONF_RETRY_INTERVAL: {"seconds": 0},
            CONF_TRIGGER_POLICY: TriggerPolicy.LAST.value,
            CONF_SHABBAT_ENTITY: shabbat.entity_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_RETRY_INTERVAL: "invalid_retry_interval"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DELAY: {"minutes": 45},
            CONF_RETRY_INTERVAL: {"minutes": 5},
            CONF_TRIGGER_POLICY: TriggerPolicy.LAST.value,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.data[CONF_RULE_ID] == entry.unique_id
    assert entry.options[CONF_AREA_ID] == room.id
    assert entry.options[CONF_ENTITIES] == [room_light.id]
    assert entry.options[CONF_DELAY_SECONDS] == 2700
    assert entry.options[CONF_RETRY_INTERVAL_SECONDS] == 300
    assert entry.options[CONF_TRIGGER_POLICY] == TriggerPolicy.LAST.value
    assert entry.options[CONF_SHABBAT_ENTITY] == shabbat.id


async def test_old_options_default_retry_interval_to_existing_shutdown_time(
    hass: HomeAssistant,
) -> None:
    async def async_turn_off(_call: ServiceCall) -> None:
        pass

    hass.services.async_register("light", SERVICE_TURN_OFF, async_turn_off)
    room = ar.async_get(hass).async_create("Legacy room")
    registry = er.async_get(hass)
    light = registry.async_get_or_create(
        "light", "test", "legacy-light", suggested_object_id="legacy_light"
    )
    light = registry.async_update_entity(light.entity_id, area_id=room.id)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy rule",
        unique_id="legacy-rule",
        data={CONF_RULE_ID: "legacy-rule"},
        options={
            CONF_NAME: "Legacy rule",
            CONF_AREA_ID: room.id,
            CONF_ENTITIES: [light.id],
            CONF_DELAY_SECONDS: 2700,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_NAME: "Legacy rule", CONF_AREA_ID: room.id}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENTITIES: [light.entity_id]}
    )

    assert result["step_id"] == "delay"
    assert _schema_default(result, CONF_DELAY) == {"minutes": 45}
    assert _schema_default(result, CONF_RETRY_INTERVAL) == {"minutes": 45}
    assert _schema_default(result, CONF_TRIGGER_POLICY) == TriggerPolicy.FIRST.value

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DELAY: {"minutes": 45},
            CONF_RETRY_INTERVAL: {"minutes": 5},
            CONF_TRIGGER_POLICY: TriggerPolicy.FIRST.value,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DELAY_SECONDS] == 2700
    assert entry.options[CONF_RETRY_INTERVAL_SECONDS] == 300
    assert entry.options[CONF_TRIGGER_POLICY] == TriggerPolicy.FIRST.value


async def test_empty_area_never_exposes_an_unrestricted_picker(
    hass: HomeAssistant,
) -> None:
    area = ar.async_get(hass).async_create("Empty")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Empty", CONF_AREA_ID: area.id}
    )

    assert result["step_id"] == "entities"
    assert result["errors"] == {"base": "no_supported_entities"}
    assert result["data_schema"].schema == {}
