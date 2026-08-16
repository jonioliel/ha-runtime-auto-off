"""Binary sensor platform for Runtime Auto-Off."""

from typing import TYPE_CHECKING, override

from homeassistant.components.binary_sensor import BinarySensorEntity

from .entity import RuntimeAutoOffEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import RuntimeAutoOffConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: RuntimeAutoOffConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities((RuntimeAutoOffAnyActiveBinarySensor(entry),))


class RuntimeAutoOffAnyActiveBinarySensor(RuntimeAutoOffEntity, BinarySensorEntity):
    """Report whether at least one selected entity is active."""

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "any_active", "any_active")

    @property
    @override
    def is_on(self) -> bool:
        return self.controller.any_active
