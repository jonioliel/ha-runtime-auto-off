"""Constants for SmplWise Runtime Auto-Off."""

from typing import Final

DOMAIN: Final = "runtime_auto_off"

CONF_NAME: Final = "name"
CONF_AREA_ID: Final = "area_id"
CONF_ENTITIES: Final = "entities"
CONF_DELAY_SECONDS: Final = "delay_seconds"
CONF_RULE_ID: Final = "rule_id"

DEFAULT_NAME: Final = "Runtime Auto-Off"
DEFAULT_DELAY_SECONDS: Final = 3600
DEFAULT_ENABLED: Final = True

STORAGE_VERSION: Final = 1
STORAGE_KEY_PREFIX: Final = DOMAIN

EVENT_ACTIVITY: Final = f"{DOMAIN}_activity"
ATTR_ENTRY_ID: Final = "entry_id"
ATTR_RULE_ID: Final = "rule_id"
ATTR_EVENT_TYPE: Final = "event_type"
ATTR_OCCURRED_AT: Final = "occurred_at"
ATTR_DATA: Final = "data"
