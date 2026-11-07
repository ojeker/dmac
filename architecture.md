# Architecture

## Dependency direction

`dm_accounting` contains the degree-minute accounting domain. It must not
depend on Home Assistant or Home Assistant-specific concepts.

`ha_adapter` contains Home Assistant integration. It may depend on
`dm_accounting`; the reverse dependency is not allowed.

## Boundaries

The accounting domain expresses dependencies on external data or services as
small `Protocol` definitions. Home Assistant adapters implement those
protocols.

`PumpPort` reads pump DM and writes an absolute target. A write result reports
whether the request was not attempted, accepted, or may have reached the pump
with an unknown result. The core controls transfer semantics and verification;
the adapter only communicates with Home Assistant.

## Transaction planning

`HeatingController` serializes start/stop commands, periodic maintenance, and
transaction completion. It retains the requested `HeatingMode` and at most one
unvalidated transaction. While a transaction is unvalidated, it issues no
further pump write. When that transaction verifies, the controller clears it
and reconciles the requested mode.

`tplanner.TransactionPlanner` provides separate state-change and maintenance
planning operations, both of which bundle the largest safe transfer.
`PumpLimits` represent hard pump boundaries; `FixedReserves` are the
deliberately chosen margins inside them.

The initial pump limits are `-3000` to `0`, with 100-DM fixed reserves.
Maintenance tops up a heating pump at `-100` or above and moves pump debt to
the account at `-2900` or below. Account-to-pump transfers target at most
`-2900`, retaining the floor reserve against a delayed read/write race; stop
transfers all pump debt toward `0`. Planning does not mutate the account.

`transaction` contains execution and verification, not planning. A transaction
uses injected pump and scheduling protocols to apply its transfer and request
verification after 90 and 180 seconds. It determines whether its own observed
pump state verifies successfully; the controller retains it until then.
After an unvalidated transaction fails its final verification, the controller
enters `ERROR` and no longer performs automatic pump writes.

An accepted or unknown pump-write outcome immediately changes the account and
becomes unvalidated; a write that was not attempted does neither. Verification
allows natural DM movement of up to 5 per minute plus a 5-DM safety margin:
13 DM at 90 seconds and 20 DM at 180 seconds. Transfers below 21 DM are
rejected before a pump write because they cannot be reliably verified, except for a small
`PUMP_TO_ACCOUNT` transfer that targets zero to stop heating. That stop
exception deliberately accepts the normal DM-window ambiguity.

`HeatingController` starts in `IDLING`. It records new start/stop intent while
another pump operation is in progress, but serializes the actual reconciliation
work. A pump/transaction failure enters terminal `ERROR`; recovery is by
creating a new controller, normally after an integration reload or restart.

A transaction stores a degree-minute value and an explicit transfer direction.
The direction is retained because not every future account entry will be
derivable from the value's sign.

## Tests

Tests live under `tests/` and mirror the production package structure.
Accounting tests use fakes for external dependencies and do not require Home
Assistant.

## Observability

The Home Assistant integration exposes `sensor.dmac_account_degree_minutes`
for the signed account balance and `binary_sensor.dmac_heating_requested` for
the requested mode. The account sensor attributes expose controller and pending
transaction diagnostics. Entities read the shared runtime state and refresh
through the integration's state-update signal; they do not store a second copy.

DMAC uses normal Python logging only, never Activity/Logbook entries.
`dm_accounting`, `ha_adapter`, and `custom_components.dmac` are independently
configurable logger namespaces. Each attempted transaction logs its completed
pump write and its final validation at `INFO`; account and pump-entity writes
are logged at `DEBUG`.
