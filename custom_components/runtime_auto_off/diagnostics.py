"""Diagnostics for Runtime Auto-Off."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import RuntimeAutoOffConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: RuntimeAutoOffConfigEntry
) -> dict[str, Any]:
    # Diagnostics must also work before setup and for disabled entries.
    controller = getattr(entry, "runtime_data", None)
    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "runtime": controller.diagnostics if controller is not None else None,
    }
