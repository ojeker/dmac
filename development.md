# DMAC development

This guide is for contributors. See [readme.md](readme.md) for installation
and use, and [architecture.md](architecture.md) for the full architecture
record.

## Structure

`dm_accounting` is the Home Assistant-independent domain. It owns the account,
transaction lifecycle, planning, and controller. It must not import Home
Assistant.

`ha_adapter` implements the domain protocols using Home Assistant APIs.
`custom_components/dmac` is the YAML integration: it constructs the runtime,
persists restart-safe state, registers services, and exposes HA entities.
Dependencies flow only toward the domain:

```text
custom_components/dmac -> ha_adapter -> dm_accounting
```

## Domain rules to preserve

- DM debt is signed: debt is negative in the account, pump, and transaction.
- A transaction has an explicit direction. Do not infer it from its signed DM
  value.
- At most one transaction may be unvalidated. Its account change is applied
  after an attempted pump write and reversed only after failed validation.
- Verification is scheduled at 90 and 180 seconds. It allows 5 DM/minute of
  natural movement plus a 5-DM margin.
- The initial physical pump range is `-3000..0`. The planner uses 100-DM
  reserves and targets no lower than `-2900` for account-to-pump transfers.
- `HeatingController` retains requested mode and serializes reconciliation.
  Pump I/O happens outside its short state lock.
- The integration persists the account balance and requested mode. Pending
  verification timers are deliberately not restored after restart.

## Home Assistant boundary

The configured pump value must be a writable integer `number.*` entity.
`HomeAssistantPumpPort` reads its DM value and writes absolute targets through
the `number.set_value` action.

The integration provides:

- `dmac.start_heating` and `dmac.stop_heating` actions;
- `sensor.dmac_account_degree_minutes`, with controller and pending-transaction
  diagnostic attributes;
- `binary_sensor.dmac_heating_requested`.

Do not put Home Assistant imports or entity IDs into `dm_accounting`.

## Logging

DMAC uses normal Python logging, not Home Assistant Activity/Logbook entries.
Useful logger namespaces are `dm_accounting`, `ha_adapter`, and
`custom_components.dmac`.

Each written transaction logs its completed pump write and final validation at
`INFO`. Account updates and writes to the HA pump entity are `DEBUG` logs. For
local diagnosis, configure Home Assistant with:

```yaml
logger:
  logs:
    dm_accounting: debug
    ha_adapter: debug
    custom_components.dmac: debug
```

## Tests and release build

Create the development environment once:

```bash
uv sync --group dev
```

Run all tests:

```bash
uv run pytest
```

Run focused suites while working on a layer:

```bash
uv run pytest tests/dm_accounting
uv run pytest tests/ha_adapter
uv run pytest tests/custom_components/dmac
uv run pytest tests/test_release_package.py
```

Production verification waits 90 and 180 seconds and maintenance runs every
600 seconds. Test-only YAML timing overrides require `DMAC_TEST_MODE=1`; do
not use them in a production configuration.

Build the manually installable custom-component archive with:

```bash
scripts/build-ha-release.sh
```

The script writes `dist/dmac-<version>.zip`.
