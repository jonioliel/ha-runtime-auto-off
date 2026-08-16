"""Diagnostics for Runtime Auto-Off."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import RuntimeAutoOffConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: RuntimeAutoOffConfigEntry
) -> dict[str, Any]:
    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": entry.runtime_data.diagnostics,
    }
