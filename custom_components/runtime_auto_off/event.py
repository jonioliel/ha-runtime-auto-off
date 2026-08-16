"""Event platform for Runtime Auto-Off."""

from typing import TYPE_CHECKING, ClassVar, override

from homeassistant.components.event import EventEntity
from homeassistant.core import callback

from .const import ATTR_OCCURRED_AT
from .entity import RuntimeAutoOffEntity
from .models import ActivityEventType

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import RuntimeAutoOffConfigEntry
    from .models import ActivityEvent


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: RuntimeAutoOffConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities((RuntimeAutoOffActivityEvent(entry),))


class RuntimeAutoOffActivityEvent(RuntimeAutoOffEntity, EventEntity):
    _attr_event_types: ClassVar[list[str]] = [
        event_type.value for event_type in ActivityEventType
    ]

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "activity", "activity")

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.async_add_activity_listener(self._async_handle_activity)
        )

    @callback
    def _async_handle_activity(self, activity: ActivityEvent) -> None:
        data = dict(activity.data)
        data[ATTR_OCCURRED_AT] = activity.occurred_at.isoformat()
        self._trigger_event(activity.event_type.value, data)
        self.async_write_ha_state()

    @callback
    @override
    def _async_controller_updated(self) -> None:
        """Only activity events update this entity."""
