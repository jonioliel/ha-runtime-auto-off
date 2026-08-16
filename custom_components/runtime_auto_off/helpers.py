"""Small helpers for SmplWise Runtime Auto-Off."""

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_registry import RegistryEntry


@callback
def effective_area_id(hass: HomeAssistant, entry: RegistryEntry) -> str | None:
    """Return an entity's own area or its device's inherited area."""
    if entry.area_id is not None:
        return entry.area_id
    if entry.device_id is None:
        return None
    device = dr.async_get(hass).async_get(entry.device_id)
    return device.area_id if device is not None else None
