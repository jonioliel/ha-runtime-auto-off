# Changelog

## [1.4.2] - 2026-11-02

- Wait up to five seconds for asynchronously reported `off` states after service
  completion, avoiding false `turn_off_not_confirmed` errors on working devices.
- Clean up state-confirmation listeners on completion, cancellation and unload;
  rearm retry timers after interrupted execution.
- Defer startup reconciliation and service calls until Home Assistant is running.
- Validate the Shabbat sensor's registry identity and require explicit `off`
  before allowing shutdown; invalid, disabled or replaced sensors fail closed.
- Honor child-device areas inherited from their parent in newer HA versions.
- Prevent Presence/Runtime Auto-Off rule switches from being selected or executed
  as targets, and support modern device registry registration.
- Keep diagnostics available for disabled or not-yet-loaded entries.
- Add regression coverage and a weekly Linux CI matrix for the minimum supported
  HA test baseline, pinned HA 2026.10.4, and the latest available test helper.

## [1.4.1] - 2026-08-20

- Added automatic GitHub Release publication for version tags so HACS can discover new versions reliably.

## [1.4.0] - 2026-08-20

- Added an optional combined Shabbat/holiday binary sensor. Automatic shutdowns and retries are blocked while it is on, and fail closed while it is unavailable.

## [1.3.0] - 2026-08-17

### Added

- Configurable first/last active-entity policy for the initial shutdown deadline.
- Device sensors for configured runtime, retry interval, next shutdown type, and
  trigger active-since time.
- Per-entity `active_since` attributes, including explicit assumed-active markers
  while an entity is unavailable.

### Changed

- Persisted active cycles now survive `unknown`, `unavailable`, missing state, and
  Home Assistant restarts; only an observed `off` state resets the runtime clock.
- Editing the retry interval immediately recalculates an already pending retry.
- Pending retries take priority over first/last policy so a failed shutdown is not
  delayed by a newly active entity.

## [1.2.0] - 2026-08-17

### Added

- A separate retry/check interval, independently configurable from the maximum
  continuous runtime.
- Backward-compatible options defaults: existing rules initially keep their prior
  behavior until the new retry interval is edited.

## [1.1.0] - 2026-08-17

### Added

- Recurring verification after the configured duration for every selected entity
  that remains active after a shutdown attempt.
- Durable per-entity retry deadlines that survive Home Assistant restarts.

### Changed

- A `turn_off` service call is now considered successful only after Home Assistant
  confirms that the entity state is `off`.

## [1.0.0] - 2026-08-16

### Added

- Area-scoped selection of explicit entities that support `turn_off`.
- Independent continuous-runtime tracking for every selected entity.
- One-shot shutdown of all selected active entities when any one reaches the limit.
- Restart-safe handled-cycle storage that prevents interval-style repeated shutdowns.
- First-class Home Assistant devices with enable, status, active, trigger, next-run,
  last-run, and activity entities.
- English and Hebrew configuration, entity, status, and event translations.
- HACS metadata, diagnostics, tests, Ruff, Hassfest, and HACS validation workflows.

[1.3.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.3.0
[1.2.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.2.0
[1.1.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.1.0
[1.0.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.0.0
