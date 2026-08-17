"""Tests for Runtime Auto-Off models."""

from datetime import UTC, datetime

from custom_components.runtime_auto_off.const import (
    CONF_AREA_ID,
    CONF_DELAY_SECONDS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_RULE_ID,
)
from custom_components.runtime_auto_off.models import (
    LastExecution,
    RuleConfig,
    RuntimeCycle,
)


def test_rule_config_normalizes_and_round_trips() -> None:
    config = RuleConfig.from_mapping(
        {
            CONF_NAME: " Living room ",
            CONF_AREA_ID: "living_room",
            CONF_ENTITIES: ["light.main", "light.main", "switch.tv"],
            CONF_DELAY_SECONDS: 600,
            CONF_RULE_ID: "rule-id",
        }
    )

    assert config.name == "Living room"
    assert config.entities == ("light.main", "switch.tv")
    assert config.delay_seconds == 600
    assert RuleConfig.from_mapping(config.as_dict()) == config


def test_cycle_and_execution_round_trip() -> None:
    now = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
    retry_at = datetime(2026, 8, 16, 10, 10, tzinfo=UTC)
    cycle = RuntimeCycle(
        "registry-id", "light.main", now, handled=True, retry_at=retry_at
    )
    execution = LastExecution(
        "light.main",
        now,
        ("light.main",),
        {"switch.off": "already_off"},
        {},
    )

    assert RuntimeCycle.from_dict(cycle.as_dict()) == cycle
    assert cycle.deadline(60) == retry_at
    assert LastExecution.from_dict(execution.as_dict()) == execution
    assert execution.succeeded


def test_malformed_persisted_models_fail_closed() -> None:
    assert RuntimeCycle.from_dict({"started_at": "not-a-time"}) is None
    assert LastExecution.from_dict({"occurred_at": "not-a-time"}) is None
