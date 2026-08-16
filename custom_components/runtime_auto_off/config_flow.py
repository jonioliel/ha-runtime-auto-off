"""Config flow for SmplWise Runtime Auto-Off."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, override
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import SERVICE_TURN_OFF
from homeassistant.core import HomeAssistant, callback, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    AreaSelector,
    DurationSelector,
    DurationSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_AREA_ID,
    CONF_DELAY_SECONDS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_RULE_ID,
    DEFAULT_DELAY_SECONDS,
    DOMAIN,
)
from .helpers import effective_area_id

CONF_DELAY = "delay"
MAX_DELAY_SECONDS = 30 * 24 * 60 * 60


def _seconds_to_duration(seconds: float) -> dict[str, float]:
    remaining = int(seconds)
    days, remaining = divmod(remaining, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes, remaining = divmod(remaining, 60)
    result: dict[str, float] = {}
    if days:
        result["days"] = days
    if hours:
        result["hours"] = hours
    if minutes:
        result["minutes"] = minutes
    if remaining or not result:
        result["seconds"] = remaining
    return result


def _duration_to_seconds(value: Mapping[str, float]) -> float:
    return timedelta(
        days=value.get("days", 0),
        hours=value.get("hours", 0),
        minutes=value.get("minutes", 0),
        seconds=value.get("seconds", 0),
        milliseconds=value.get("milliseconds", 0),
    ).total_seconds()


@callback
def _resolve_entity_id(hass: HomeAssistant, reference: str) -> str | None:
    return er.async_resolve_entity_id(er.async_get(hass), reference)


@callback
def _resolve_entity_ids(
    hass: HomeAssistant, references: list[str]
) -> tuple[list[str], bool]:
    resolved: list[str] = []
    unresolved = False
    for reference in references:
        entity_id = _resolve_entity_id(hass, reference)
        if entity_id is None:
            unresolved = True
        elif entity_id not in resolved:
            resolved.append(entity_id)
    return resolved, unresolved


@callback
def _display_entity_ids(hass: HomeAssistant, references: list[str]) -> list[str]:
    displayed: list[str] = []
    for reference in references:
        entity_id = _resolve_entity_id(hass, reference) or reference
        if entity_id not in displayed:
            displayed.append(entity_id)
    return displayed


@callback
def _canonical_reference(hass: HomeAssistant, entity_id: str) -> str:
    entry = er.async_get(hass).async_get(entity_id)
    return entry.id if entry is not None else entity_id


@callback
def _turn_off_entities_in_area(
    hass: HomeAssistant, area_id: str, selected: list[str] | None = None
) -> list[str]:
    registry = er.async_get(hass)
    candidates = {
        entry.entity_id
        for entry in registry.entities.values()
        if not entry.disabled
        and effective_area_id(hass, entry) == area_id
        and hass.services.has_service(
            split_entity_id(entry.entity_id)[0], SERVICE_TURN_OFF
        )
    }
    resolved_selected, _ = _resolve_entity_ids(hass, selected or [])
    candidates.update(resolved_selected)
    return sorted(candidates)


def _required_marker(key: str, value: str | None) -> vol.Required:
    return vol.Required(key, default=value) if value else vol.Required(key)


class _RuleFlowMixin:
    hass: HomeAssistant
    _working: dict[str, Any]

    def _room_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_NAME, default=self._working.get(CONF_NAME, "")
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                _required_marker(
                    CONF_AREA_ID, self._working.get(CONF_AREA_ID)
                ): AreaSelector(),
            }
        )

    def _entities_schema(self, candidates: list[str]) -> vol.Schema:
        if not candidates:
            return vol.Schema({})
        selected = _display_entity_ids(
            self.hass, list(self._working.get(CONF_ENTITIES, []))
        )
        return vol.Schema(
            {
                vol.Required(CONF_ENTITIES, default=selected): EntitySelector(
                    EntitySelectorConfig(
                        include_entities=candidates,
                        multiple=True,
                        reorder=True,
                    )
                )
            }
        )

    def _delay_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_DELAY,
                    default=_seconds_to_duration(
                        self._working.get(CONF_DELAY_SECONDS, DEFAULT_DELAY_SECONDS)
                    ),
                ): DurationSelector(
                    DurationSelectorConfig(enable_day=True, enable_second=True)
                )
            }
        )

    def _accept_room(self, user_input: dict[str, Any]) -> dict[str, str]:
        name = user_input[CONF_NAME].strip()
        if not name:
            return {CONF_NAME: "name_required"}
        old_area = self._working.get(CONF_AREA_ID)
        self._working.update(user_input)
        self._working[CONF_NAME] = name
        if old_area is not None and old_area != user_input[CONF_AREA_ID]:
            self._working.pop(CONF_ENTITIES, None)
        return {}

    def _accept_entities(self, user_input: dict[str, Any]) -> dict[str, str]:
        references = list(dict.fromkeys(user_input.get(CONF_ENTITIES, [])))
        entities, unresolved = _resolve_entity_ids(self.hass, references)
        if unresolved:
            return {CONF_ENTITIES: "entity_not_found"}
        if not entities:
            return {CONF_ENTITIES: "entities_required"}
        allowed = set(
            _turn_off_entities_in_area(self.hass, self._working[CONF_AREA_ID])
        )
        if not set(entities) <= allowed:
            return {CONF_ENTITIES: "entity_not_allowed"}
        self._working[CONF_ENTITIES] = [
            _canonical_reference(self.hass, entity_id) for entity_id in entities
        ]
        return {}

    def _accept_delay(self, user_input: dict[str, Any]) -> dict[str, str]:
        delay = _duration_to_seconds(user_input[CONF_DELAY])
        if delay < 0 or delay > MAX_DELAY_SECONDS:
            return {CONF_DELAY: "invalid_delay"}
        self._working[CONF_DELAY_SECONDS] = delay
        return {}


class RuntimeAutoOffConfigFlow(_RuleFlowMixin, ConfigFlow, domain=DOMAIN):
    """Create a runtime rule."""

    VERSION = 1

    def __init__(self) -> None:
        self._working = {}

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> RuntimeAutoOffOptionsFlow:
        return RuntimeAutoOffOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._accept_room(user_input)
            if not errors:
                return await self.async_step_entities()
        return self.async_show_form(
            step_id="user", data_schema=self._room_schema(), errors=errors
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidates = _turn_off_entities_in_area(
            self.hass,
            self._working[CONF_AREA_ID],
            self._working.get(CONF_ENTITIES),
        )
        errors: dict[str, str] = {}
        if not candidates:
            errors["base"] = "no_supported_entities"
        elif user_input is not None:
            errors = self._accept_entities(user_input)
            if not errors:
                return await self.async_step_delay()
        return self.async_show_form(
            step_id="entities",
            data_schema=self._entities_schema(candidates),
            errors=errors,
        )

    async def async_step_delay(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._accept_delay(user_input)
            if not errors:
                rule_id = uuid4().hex
                await self.async_set_unique_id(rule_id)
                return self.async_create_entry(
                    title=self._working[CONF_NAME],
                    data={CONF_RULE_ID: rule_id},
                    options=self._working,
                )
        return self.async_show_form(
            step_id="delay", data_schema=self._delay_schema(), errors=errors
        )


class RuntimeAutoOffOptionsFlow(_RuleFlowMixin, OptionsFlowWithReload):
    """Edit and reload a runtime rule."""

    def __init__(self) -> None:
        self._working = {}

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._working:
            self._working = dict(self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._accept_room(user_input)
            if not errors:
                return await self.async_step_entities()
        return self.async_show_form(
            step_id="init", data_schema=self._room_schema(), errors=errors
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidates = _turn_off_entities_in_area(
            self.hass,
            self._working[CONF_AREA_ID],
            self._working.get(CONF_ENTITIES),
        )
        errors: dict[str, str] = {}
        if not candidates:
            errors["base"] = "no_supported_entities"
        elif user_input is not None:
            errors = self._accept_entities(user_input)
            if not errors:
                return await self.async_step_delay()
        return self.async_show_form(
            step_id="entities",
            data_schema=self._entities_schema(candidates),
            errors=errors,
        )

    async def async_step_delay(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._accept_delay(user_input)
            if not errors:
                if self.config_entry.title != self._working[CONF_NAME]:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, title=self._working[CONF_NAME]
                    )
                return self.async_create_entry(title="", data=self._working)
        return self.async_show_form(
            step_id="delay", data_schema=self._delay_schema(), errors=errors
        )
