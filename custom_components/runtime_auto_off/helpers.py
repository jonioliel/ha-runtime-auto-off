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
    registry = dr.async_get(hass)
    device = registry.async_get(entry.device_id)
    seen: set[str] = set()
    while device is not None and device.id not in seen:
        seen.add(device.id)
        if device.area_id is not None:
            return device.area_id
        parent_id = getattr(device, "parent_device_id", None)
        device = registry.async_get(parent_id) if parent_id is not None else None
    return None
