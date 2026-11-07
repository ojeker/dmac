"""Constants for the DMAC Home Assistant integration."""

DOMAIN = "dmac"

CONF_PUMP_ENTITY_ID = "pump_entity_id"
CONF_RUNNING_STOP_RESERVE = "running_stop_reserve"
CONF_IDLING_FLOOR_RESERVE = "idling_floor_reserve"
CONF_FIRST_VERIFICATION_DELAY_SECONDS = "first_verification_delay_seconds"
CONF_FINAL_VERIFICATION_DELAY_SECONDS = "final_verification_delay_seconds"
CONF_MAINTENANCE_INTERVAL_SECONDS = "maintenance_interval_seconds"

SERVICE_START_HEATING = "start_heating"
SERVICE_STOP_HEATING = "stop_heating"

STORAGE_KEY = "dmac.state"
STORAGE_VERSION = 1

SIGNAL_STATE_UPDATED = "dmac_state_updated"
