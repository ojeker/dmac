# DMAC for Home Assistant (**D**egree **M**inute **Ac**count)

DMAC moves degree-minute (DM) debt between a heat pump's writable Home
Assistant number entity and a persisted DM account. It can be used for soft
steering of when the pump starts heating and how long it runs.

> [!WARNING]
> DMAC writes a real heat-pump control value. Install it only when you
> understand the configured entity and have tested your heat-pump integration.
> Back up your Home Assistant configuration before continuing.

## Requirements

- Home Assistant 2026.11.0, the version against which this release is tested.
- A writable, integer-valued `number.*` entity exposing your pump's degree
  minutes. DMAC writes it through Home Assistant's `number.set_value` action.
- Access to the Home Assistant configuration directory and permission to
  restart Home Assistant.

DMAC manages one controller per Home Assistant instance. Do not install Python
packages directly into a managed Home Assistant installation; use the release
archive below.

## Install

1. Download the `dmac-<version>.zip` release archive.
2. Back up your Home Assistant configuration directory.
3. Extract the archive into that directory. The resulting path must be exactly:

   ```text
   <config>/custom_components/dmac/manifest.json
   ```

   Do not leave an extra directory level such as
   `<config>/dmac-<version>/custom_components/...`.
4. Restart Home Assistant.
5. Open Developer Tools and confirm that `dmac.start_heating` and
   `dmac.stop_heating` are available. If they are absent, check the Home
   Assistant log before adding automations.

## Configure

Add one `dmac:` block to `configuration.yaml`, then restart Home Assistant:

```yaml
dmac:
  pump_entity_id: number.your_pump_degree_minutes
  running_stop_reserve: 100
  idling_floor_reserve: 100
```

`pump_entity_id` must name the writable `number.*` entity that represents the
pump's degree-minute value. Both reserve values are positive degree-minute
magnitudes. The initial project defaults are 100 DM for each reserve; adjust
them only when you understand the operating bounds of your heat pump.

Configuration changes take effect only after a Home Assistant restart.

## Use in automations

DMAC registers two no-argument actions:

- `dmac.start_heating` requests heating and immediately reconciles the pump.
- `dmac.stop_heating` requests idling and immediately reconciles the pump.

For example, an automation action can call:

```yaml
action: dmac.start_heating
```

or:

```yaml
action: dmac.stop_heating
```

Confirm the pump entity and your surrounding safety automations before calling
either action. A successful Home Assistant service call only confirms that the
request was accepted; DMAC verifies the observed pump value after 90 and 180
seconds. It also runs maintenance every ten minutes.

## Persistence, upgrades, and reset

DMAC stores its account balance and requested mode in
`<config>/.storage/dmac.state`. It restores those values after a restart, but
deliberately discards a transaction that was awaiting verification. Restart
Home Assistant only while no pump write is pending.

To upgrade, back up the configuration directory, replace the
`custom_components/dmac` directory with the newer release contents, and
restart Home Assistant.

To remove DMAC, stop Home Assistant and remove `custom_components/dmac`. To
reset the DM account as well, first back up `.storage/dmac.state`, then remove
that file while Home Assistant is stopped. Resetting the file is destructive
and cannot be undone without the backup.

## Troubleshooting

- **No DMAC actions appear:** Check the extracted directory layout and restart
  Home Assistant; then inspect the log for import or YAML-validation errors.
- **Configuration is rejected:** Confirm the entity starts with `number.` and
  both reserves are positive integers, not quoted strings or booleans.
- **Pump is unavailable or does not use an integer state:** Fix the underlying
  pump integration first. DMAC does not invent a replacement DM value.
- **Controller enters an error state:** Automatic writes stop after a pump or
  final-verification failure. Inspect the Home Assistant log and restart after
  correcting the underlying issue.

## Development and test timing

For development, create the tested environment and run the suite:

```bash
uv sync --group dev
.venv/bin/pytest -q
scripts/build-ha-release.sh
```

The release builder creates `dist/dmac-<version>.zip`. Docker/test fixtures may
set `DMAC_TEST_MODE=1` and use short timing values in the `dmac:` block:

```yaml
first_verification_delay_seconds: 1
final_verification_delay_seconds: 2
maintenance_interval_seconds: 1
```

These timing keys are test-only. Do not add them to a production Home
Assistant configuration.
