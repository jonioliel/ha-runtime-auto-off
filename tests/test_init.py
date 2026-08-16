"""Tests for integration unload orchestration."""

from unittest.mock import AsyncMock, Mock

from custom_components.runtime_auto_off import PLATFORMS, async_unload_entry


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
