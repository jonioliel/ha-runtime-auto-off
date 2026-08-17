"""Typed models for SmplWise Runtime Auto-Off."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Self

from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA_ID,
    CONF_DELAY_SECONDS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_RULE_ID,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_NAME,
)


class Status(StrEnum):
    """Runtime status of a time rule."""

    INITIALIZING = "initializing"
    DISABLED = "disabled"
    IDLE = "idle"
    COUNTDOWN = "countdown"
    EXECUTING = "executing"
    COMPLETED = "completed"
    SENSOR_UNAVAILABLE = "sensor_unavailable"
    ERROR = "error"


class ActivityEventType(StrEnum):
    """Activity emitted by a time rule."""

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    EXECUTED = "executed"
    NO_ACTION = "no_action"
    FAILED = "failed"


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _string_sequence(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Sequence[Any] = (value,)
    elif isinstance(value, Sequence):
        values = value
    else:
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in values if isinstance(item, str) and item.strip()
        )
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt_util.parse_datetime(value)
    except ValueError:
        return None
    if parsed is None or parsed.tzinfo is None:
        return None
    return dt_util.as_utc(parsed)


def _string_mapping(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str):
            return None
        result[key] = item[:500]
    return result


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Configuration for one runtime rule."""

    name: str
    area_id: str | None
    entities: tuple[str, ...]
    delay_seconds: float
    rule_id: str = ""

    @classmethod
    def from_mapping(cls, options: Mapping[str, Any]) -> Self:
        raw_delay = options.get(CONF_DELAY_SECONDS, DEFAULT_DELAY_SECONDS)
        try:
            delay = float(raw_delay) if not isinstance(raw_delay, bool) else math.nan
        except (TypeError, ValueError):
            delay = math.nan
        if not math.isfinite(delay):
            delay = float(DEFAULT_DELAY_SECONDS)
        return cls(
            name=_optional_string(options.get(CONF_NAME)) or DEFAULT_NAME,
            area_id=_optional_string(options.get(CONF_AREA_ID)),
            entities=_string_sequence(options.get(CONF_ENTITIES)),
            delay_seconds=max(0.0, delay),
            rule_id=_optional_string(options.get(CONF_RULE_ID)) or "",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            CONF_NAME: self.name,
            CONF_AREA_ID: self.area_id,
            CONF_ENTITIES: list(self.entities),
            CONF_DELAY_SECONDS: self.delay_seconds,
            CONF_RULE_ID: self.rule_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeCycle:
    """One continuous active period for a selected entity."""

    stable_key: str
    entity_id: str
    started_at: datetime
    handled: bool = False
    retry_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.stable_key or not self.entity_id or self.started_at.tzinfo is None:
            raise ValueError("A cycle requires identity and timezone-aware time")
        object.__setattr__(self, "started_at", dt_util.as_utc(self.started_at))
        if self.retry_at is not None:
            if self.retry_at.tzinfo is None:
                raise ValueError("A retry time must be timezone-aware")
            object.__setattr__(self, "retry_at", dt_util.as_utc(self.retry_at))

    def deadline(self, delay_seconds: float) -> datetime:
        """Return the next initial or retry shutdown deadline."""
        return self.retry_at or self.started_at + timedelta(seconds=delay_seconds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "entity_id": self.entity_id,
            "started_at": self.started_at.isoformat(),
            "handled": self.handled,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self | None:
        key = _optional_string(data.get("stable_key"))
        entity_id = _optional_string(data.get("entity_id"))
        started_at = _parse_datetime(data.get("started_at"))
        if key is None or entity_id is None or started_at is None:
            return None
        raw_retry_at = data.get("retry_at")
        retry_at = _parse_datetime(raw_retry_at)
        if raw_retry_at is not None and retry_at is None:
            return None
        return cls(
            key,
            entity_id,
            started_at,
            data.get("handled") is True,
            retry_at,
        )


@dataclass(frozen=True, slots=True)
class LastExecution:
    """Result of the most recent automatic shutdown."""

    trigger_entity: str
    occurred_at: datetime
    successful_entities: tuple[str, ...]
    skipped_entities: Mapping[str, str]
    failed_entities: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.trigger_entity or self.occurred_at.tzinfo is None:
            raise ValueError("Execution requires a trigger and aware time")
        object.__setattr__(self, "occurred_at", dt_util.as_utc(self.occurred_at))
        object.__setattr__(self, "successful_entities", tuple(self.successful_entities))
        object.__setattr__(self, "skipped_entities", dict(self.skipped_entities))
        object.__setattr__(self, "failed_entities", dict(self.failed_entities))

    @property
    def succeeded(self) -> bool:
        return not self.failed_entities

    def as_dict(self) -> dict[str, Any]:
        return {
            "trigger_entity": self.trigger_entity,
            "occurred_at": self.occurred_at.isoformat(),
            "successful_entities": list(self.successful_entities),
            "skipped_entities": dict(self.skipped_entities),
            "failed_entities": dict(self.failed_entities),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self | None:
        trigger = _optional_string(data.get("trigger_entity"))
        occurred = _parse_datetime(data.get("occurred_at"))
        successes = _string_sequence(data.get("successful_entities"))
        skipped = _string_mapping(data.get("skipped_entities"))
        failed = _string_mapping(data.get("failed_entities"))
        if trigger is None or occurred is None or skipped is None or failed is None:
            return None
        return cls(trigger, occurred, successes, skipped, failed)


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """One observable controller activity."""

    event_type: ActivityEventType
    occurred_at: datetime
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("Activity time must be timezone-aware")
        object.__setattr__(self, "occurred_at", dt_util.as_utc(self.occurred_at))
        object.__setattr__(self, "data", dict(self.data))

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "data": dict(self.data),
        }
