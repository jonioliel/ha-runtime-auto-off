"""Integration-device and entity registration tests."""

from typing import TYPE_CHECKING

from homeassistant.const import SERVICE_TURN_OFF, STATE_OFF
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.runtime_auto_off.const import (
    CONF_AREA_ID,
    CONF_DELAY_SECONDS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_RULE_ID,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall


async def test_rule_device_owns_every_generated_entity(hass: HomeAssistant) -> None:
    async def async_turn_off(_call: ServiceCall) -> None:
        pass

    hass.services.async_register("light", SERVICE_TURN_OFF, async_turn_off)
    area = ar.async_get(hass).async_create("Office")
    registry = er.async_get(hass)
    light = registry.async_get_or_create(
        "light", "test", "office-light", suggested_object_id="office_light"
    )
    light = registry.async_update_entity(light.entity_id, area_id=area.id)
    hass.states.async_set(light.entity_id, STATE_OFF)

    rule_id = "office-runtime-rule"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Office runtime",
        unique_id=rule_id,
        data={CONF_RULE_ID: rule_id},
        options={
            CONF_NAME: "Office runtime",
            CONF_AREA_ID: area.id,
            CONF_ENTITIES: [light.id],
            CONF_DELAY_SECONDS: 600,
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, rule_id), entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "SmplWise (SW)"
    assert device.model == "Runtime shutdown rule"
    assert device.configuration_url == (
        "homeassistant://config/integrations/integration/"
        f"{DOMAIN}#config_entry={entry.entry_id}"
    )

    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {item.unique_id for item in entities} == {
        f"{rule_id}_activity",
        f"{rule_id}_any_active",
        f"{rule_id}_configured_runtime",
        f"{rule_id}_enabled",
        f"{rule_id}_last_shutdown",
        f"{rule_id}_next_shutdown",
        f"{rule_id}_next_shutdown_kind",
        f"{rule_id}_retry_interval",
        f"{rule_id}_status",
        f"{rule_id}_trigger_active_since",
        f"{rule_id}_trigger_entity",
    }
    assert {item.device_id for item in entities} == {device.id}
    assert all(item.platform == DOMAIN for item in entities)

    assert await hass.config_entries.async_unload(entry.entry_id)
