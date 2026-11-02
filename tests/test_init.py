"""Tests for integration unload orchestration."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.runtime_auto_off import (
    PLATFORMS,
    async_setup_entry,
    async_unload_entry,
)


@pytest.mark.parametrize("modern_registry", [True, False])
async def test_device_registration_supports_new_and_legacy_ha(
    modern_registry: bool,
) -> None:
    register = Mock()
    registry = (
        SimpleNamespace(async_get_or_create_from_info=register)
        if modern_registry
        else SimpleNamespace(async_get_or_create=register)
    )
    # A non-mapping reproduces the DeviceInfo dataclass API introduced in HA 2026.11.
    device_info = object() if modern_registry else {"name": "Room"}
    controller = Mock(
        async_setup=AsyncMock(), async_unload=AsyncMock(), config=Mock(name="Room")
    )
    entry = Mock(entry_id="entry")
    hass = Mock(
        config_entries=Mock(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(),
        )
    )
    module = "custom_components.runtime_auto_off"
    with (
        patch(f"{module}._resolve_runtime_config", return_value={}),
        patch(f"{module}.RuntimeAutoOffController", return_value=controller),
        patch(f"{module}.rule_device_info", return_value=device_info),
        patch(f"{module}.dr.async_get", return_value=registry),
    ):
        assert await async_setup_entry(hass, entry)

    if modern_registry:
        register.assert_called_once_with(
            config_entry_id=entry.entry_id, device_info=device_info
        )
    else:
        register.assert_called_once_with(config_entry_id=entry.entry_id, name="Room")
    controller.async_setup.assert_awaited_once()


async def test_rejected_platform_unload_resumes_controller() -> None:
    order: list[str] = []
    controller = Mock(
        async_stop=AsyncMock(side_effect=lambda: order.append("stop")),
        async_resume=AsyncMock(side_effect=lambda: order.append("resume")),
        async_unload=AsyncMock(side_effect=lambda: order.append("unload")),
    )
    entry = Mock(runtime_data=controller)
    config_entries = Mock(
        async_unload_platforms=AsyncMock(
            side_effect=lambda *_args: order.append("platforms") or False
        )
    )
    hass = Mock(config_entries=config_entries)

    assert await async_unload_entry(hass, entry) is False
    assert order == ["stop", "platforms", "resume"]
    config_entries.async_unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
    controller.async_unload.assert_not_awaited()
