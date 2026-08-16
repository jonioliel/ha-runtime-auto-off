"""Switch platform for Runtime Auto-Off."""

from typing import TYPE_CHECKING, override

from homeassistant.components.switch import SwitchEntity

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
    async_add_entities((RuntimeAutoOffEnabledSwitch(entry),))


class RuntimeAutoOffEnabledSwitch(RuntimeAutoOffEntity, SwitchEntity):
    """Enable or pause a runtime rule."""

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "enabled", "enabled")

    @property
    @override
    def is_on(self) -> bool:
        return self.controller.enabled

    @override
    async def async_turn_on(self, **_kwargs: object) -> None:
        await self.controller.async_set_enabled(True)

    @override
    async def async_turn_off(self, **_kwargs: object) -> None:
        await self.controller.async_set_enabled(False)
