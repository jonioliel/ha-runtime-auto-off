"""Binary sensor platform for Runtime Auto-Off."""

from typing import TYPE_CHECKING, Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory

from .entity import RuntimeAutoOffEntity
from .models import Status

if TYPE_CHECKING:
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
            RuntimeAutoOffAnyActiveBinarySensor(entry),
            RuntimeAutoOffProblemBinarySensor(entry),
        )
    )


class RuntimeAutoOffProblemBinarySensor(RuntimeAutoOffEntity, BinarySensorEntity):
    """Expose failures without requiring users to inspect Recorder history."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "problem", "problem")

    @property
    @override
    def is_on(self) -> bool:
        if not self.controller.enabled or self.controller.status is Status.INITIALIZING:
            return False
        return (
            bool(self.controller.target_issues)
            or self.controller.status in (Status.ERROR, Status.SENSOR_UNAVAILABLE)
            or bool(
                self.controller.last_execution
                and self.controller.last_execution.failed_entities
            )
        )

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        execution = self.controller.last_execution
        return {
            **super().extra_state_attributes,
            "rule_enabled": self.controller.enabled,
            "rule_status": self.controller.status.value,
            "target_issues": self.controller.target_issues,
            "last_failed_entities": dict(execution.failed_entities)
            if execution
            else {},
            "trigger_policy": self.controller.config.trigger_policy.value,
            "deadline_scope": "selected_group",
            "selected_entities": list(self.controller.config.entities),
        }


class RuntimeAutoOffAnyActiveBinarySensor(RuntimeAutoOffEntity, BinarySensorEntity):
    """Report whether at least one selected entity is active."""

    def __init__(self, entry: RuntimeAutoOffConfigEntry) -> None:
        super().__init__(entry, "any_active", "any_active")

    @property
    @override
    def is_on(self) -> bool:
        return self.controller.any_active

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        attributes = super().extra_state_attributes
        attributes["active_since"] = {
            entity_id: started_at.isoformat()
            for entity_id, started_at in self.controller.active_since.items()
        }
        attributes["assumed_active_while_unavailable"] = sorted(
            set(self.controller.active_since)
            & set(self.controller.unavailable_entities)
        )
        return attributes
