# Architecture

## Purpose

Manages JSON/JSONC bot configuration from Discord with permissions, backups and runtime overrides.

## Boundary

The public repository documents only the system boundary. The production edition contains private implementation details, persistence schemas, operational thresholds, adapters, credentials and deployment configuration.

## Components

- **Discord interaction layer** — buttons, forms, commands and/or event listeners.
- **Domain service layer** — validates state and executes the project-specific workflow.
- **Persistence/integration layer** — private production storage and external adapters.
- **Observability layer** — staff logs, error handling and operational feedback.

## Workflow

1. Select config source
2. Select section and setting
3. Validate permission and value
4. Create safe backup
5. Apply sanitized change

## Why the implementation is private

The production code is a commercial/private implementation. The portfolio edition intentionally prevents direct deployment while still documenting the engineering scope.
