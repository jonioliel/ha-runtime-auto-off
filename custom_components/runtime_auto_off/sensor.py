"""Sensor platform for Runtime Auto-Off."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTime

from .entity import RuntimeAutoOffEntity
from .models import ShutdownKind, Status

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
            RuntimeAutoOffTriggerActiveSinceSensor(entry),
            RuntimeAutoOffNextShutdownSensor(entry),
            RuntimeAutoOffNextShutdownKindSensor(entry),
            RuntimeAutoOffLastShutdownSensor(entry),
            RuntimeAutoOffConfiguredRuntimeSensor(entry),
            RuntimeAutoOffRetryIntervalSensor(entry),
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


class RuntimeAutoOffTriggerActiveSinceSensor(RuntimeAutoOffEntity, SensorEntity):
    """Expose when the currently triggering entity became active."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "trigger_active_since", "trigger_active_since")

    @property
    @override
    def native_value(self) -> datetime | None:
        return self.controller.trigger_started_at


class RuntimeAutoOffNextShutdownSensor(RuntimeAutoOffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "next_shutdown", "next_shutdown")

    @property
    @override
    def native_value(self) -> datetime | None:
        return self.controller.deadline


class RuntimeAutoOffNextShutdownKindSensor(RuntimeAutoOffEntity, SensorEntity):
    """Expose whether the next deadline is an initial shutdown or retry."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [kind.value for kind in ShutdownKind]

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "next_shutdown_kind", "next_shutdown_kind")

    @property
    @override
    def native_value(self) -> str | None:
        kind = self.controller.next_shutdown_kind
        return kind.value if kind is not None else None


class RuntimeAutoOffLastShutdownSensor(RuntimeAutoOffEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "last_shutdown", "last_shutdown")

    @property
    @override
    def native_value(self) -> datetime | None:
        execution = self.controller.last_execution
        return execution.occurred_at if execution is not None else None


class RuntimeAutoOffConfiguredRuntimeSensor(RuntimeAutoOffEntity, SensorEntity):
    """Expose the configured continuous runtime limit."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "configured_runtime", "configured_runtime")

    @property
    @override
    def native_value(self) -> float:
        return self.controller.config.delay_seconds


class RuntimeAutoOffRetryIntervalSensor(RuntimeAutoOffEntity, SensorEntity):
    """Expose the configured retry/check interval."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "retry_interval", "retry_interval")

    @property
    @override
    def native_value(self) -> float:
        return float(self.controller.config.retry_interval_seconds or 0)
