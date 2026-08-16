"""Shared entity support for Runtime Auto-Off."""

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from . import RuntimeAutoOffConfigEntry
from .const import CONF_AREA_ID, CONF_NAME, CONF_RULE_ID
from .controller import RuntimeAutoOffController
from .device import rule_device_info


class RuntimeAutoOffEntity(Entity):
    """Base class for entities belonging to one runtime rule."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: RuntimeAutoOffConfigEntry, key: str, translation_key: str
    ) -> None:
        self.controller: RuntimeAutoOffController = entry.runtime_data
        rule_id = str(entry.data[CONF_RULE_ID])
        self._attr_unique_id = f"{rule_id}_{key}"
        self._attr_translation_key = translation_key
        self._attr_device_info = rule_device_info(entry, self.controller.config.name)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.async_add_listener(self._async_controller_updated)
        )

    @callback
    def _async_controller_updated(self) -> None:
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            CONF_AREA_ID: self.controller.config.area_id,
            CONF_NAME: self.controller.config.name,
        }
