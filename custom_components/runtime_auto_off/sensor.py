"""Sensor platform for Runtime Auto-Off."""

from typing import TYPE_CHECKING, ClassVar, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from .entity import RuntimeAutoOffEntity
from .models import Status

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import RuntimeAutoOffConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: RuntimeAutoOffConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        (
            RuntimeAutoOffStatusSensor(entry),
            RuntimeAutoOffTriggerEntitySensor(entry),
            RuntimeAutoOffNextShutdownSensor(entry),
            RuntimeAutoOffLastShutdownSensor(entry),
        )
    )


class RuntimeAutoOffStatusSensor(RuntimeAutoOffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [status.value for status in Status]

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "status", "status")

    @property
    @override
    def native_value(self) -> str:
        return self.controller.status.value


class RuntimeAutoOffTriggerEntitySensor(RuntimeAutoOffEntity, SensorEntity):
    """Expose the entity whose active period reaches the limit first."""

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "trigger_entity", "trigger_entity")

    @property
    @override
    def native_value(self) -> str | None:
        return self.controller.trigger_entity


class RuntimeAutoOffNextShutdownSensor(RuntimeAutoOffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "next_shutdown", "next_shutdown")

    @property
    @override
    def native_value(self) -> datetime | None:
        return self.controller.deadline


class RuntimeAutoOffLastShutdownSensor(RuntimeAutoOffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "last_shutdown", "last_shutdown")

    @property
    @override
    def native_value(self) -> datetime | None:
        execution = self.controller.last_execution
        return execution.occurred_at if execution is not None else None
