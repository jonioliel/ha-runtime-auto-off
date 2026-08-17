# Changelog

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

[1.1.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.1.0
[1.0.0]: https://github.com/jonioliel/ha-runtime-auto-off/releases/tag/v1.0.0
