"""Device metadata for Runtime Auto-Off rules."""

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_RULE_ID, DOMAIN

if TYPE_CHECKING:
    from . import RuntimeAutoOffConfigEntry


def rule_device_info(entry: RuntimeAutoOffConfigEntry, name: str) -> DeviceInfo:
    """Return the shared device definition for one runtime rule."""
    rule_id = str(entry.data[CONF_RULE_ID])
    return DeviceInfo(
        identifiers={(DOMAIN, rule_id)},
        configuration_url=(
            "homeassistant://config/integrations/integration/"
            f"{DOMAIN}#config_entry={entry.entry_id}"
        ),
        manufacturer="SmplWise (SW)",
        model="Runtime shutdown rule",
        name=name,
    )
