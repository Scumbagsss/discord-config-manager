# Discord Config Manager

> **Portfolio showcase — production source is private and this repository is intentionally non-runnable.**

Manages JSON/JSONC bot configuration from Discord with permissions, backups and runtime overrides.

## What it demonstrates

- JSON/JSONC configuration editor
- Runtime overrides
- Backup-before-write workflow
- Source/section/setting navigation
- Role and channel selectors
- Sensitive-field filtering

## Technology

Python • discord.py • JSON/JSONC • File backups • Dynamic UI

## High-level workflow

1. Select config source
2. Select section and setting
3. Validate permission and value
4. Create safe backup
5. Apply sanitized change

## Public interface preview

The public skeleton exposes only the architectural surface:

- `list_sources(...)`
- `list_sections(...)`
- `validate_change(...)`
- `create_backup(...)`
- `apply_override(...)`

The production implementations behind these methods are withheld. See [`NOTICE.md`](NOTICE.md).

## Repository contents

- `src/public_interface.py` — non-runnable interface skeleton;
- `docs/ARCHITECTURE.md` — high-level design;
- `examples/config.example.jsonc` — sanitized configuration shape;
- `LICENSE` — explicit all-rights-reserved notice.

## Status

Production-tested private project / portfolio edition.
