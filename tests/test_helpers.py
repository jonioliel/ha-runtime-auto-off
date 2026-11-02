"""Area inheritance tests, including Home Assistant child devices."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from custom_components.runtime_auto_off.helpers import effective_area_id


@pytest.mark.parametrize(
    ("entity_area", "child_area", "expected"),
    [
        (None, None, "parent-room"),
        (None, "child-room", "child-room"),
        ("entity-room", "child-room", "entity-room"),
    ],
)
def test_child_device_inherits_parent_area(
    entity_area: str | None, child_area: str | None, expected: str
) -> None:
    devices = {
        "child": SimpleNamespace(
            id="child", area_id=child_area, parent_device_id="parent"
        ),
        "parent": SimpleNamespace(id="parent", area_id="parent-room"),
    }
    registry = Mock(async_get=devices.get)
    entity = SimpleNamespace(area_id=entity_area, device_id="child")
    with patch(
        "custom_components.runtime_auto_off.helpers.dr.async_get", return_value=registry
    ):
        assert effective_area_id(Mock(), entity) == expected


def test_device_without_parent_or_area_is_unassigned() -> None:
    registry = Mock(
        async_get=Mock(return_value=SimpleNamespace(id="device", area_id=None))
    )
    entity = SimpleNamespace(area_id=None, device_id="device")
    with patch(
        "custom_components.runtime_auto_off.helpers.dr.async_get", return_value=registry
    ):
        assert effective_area_id(Mock(), entity) is None
