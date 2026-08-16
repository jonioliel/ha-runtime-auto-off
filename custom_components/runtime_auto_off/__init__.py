"""SmplWise Runtime Auto-Off integration."""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_ENTITIES
from .controller import RuntimeAutoOffController
from .device import rule_device_info
from .models import RuleConfig

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.SENSOR,
    Platform.SWITCH,
]

type RuntimeAutoOffConfigEntry = ConfigEntry[RuntimeAutoOffController]


def _resolve_runtime_config(
    hass: HomeAssistant, entry: RuntimeAutoOffConfigEntry
) -> dict[str, Any]:
    """Merge data/options and resolve rename-safe registry references."""
    config: dict[str, Any] = {**entry.data, **entry.options}
    registry = er.async_get(hass)

    def resolve(reference: str) -> str:
        try:
            return er.async_validate_entity_id(registry, reference)
        except vol.Invalid:
            return reference

    if isinstance(entities := config.get(CONF_ENTITIES), list):
        config[CONF_ENTITIES] = [
            resolve(reference) if isinstance(reference, str) else reference
            for reference in entities
        ]
    return config


async def async_setup_entry(
    hass: HomeAssistant, entry: RuntimeAutoOffConfigEntry
) -> bool:
    """Set up one runtime rule."""
    controller = RuntimeAutoOffController(
        hass,
        entry.entry_id,
        RuleConfig.from_mapping(_resolve_runtime_config(hass, entry)),
    )
    entry.runtime_data = controller
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        **rule_device_info(entry, controller.config.name),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    try:
        await controller.async_setup()
    except Exception:
        with suppress(Exception):
            await controller.async_unload()
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RuntimeAutoOffConfigEntry
) -> bool:
    """Unload one runtime rule."""
    controller = entry.runtime_data
    await controller.async_stop()
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except BaseException:
        await controller.async_resume()
        raise
    if not unloaded:
        await controller.async_resume()
        return False
    await controller.async_unload()
    return True
