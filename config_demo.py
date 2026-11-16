"""Runnable synthetic configuration backend with optimistic versions and SQLite.

This is NOT the private Discord configuration manager. It edits only a small
explicit whitelist of harmless demo settings and never reads production files.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Mapping


DEFAULTS: dict[str, int | str | bool] = {
    "support.max_open_tickets": 8,
    "support.allow_attachments": True,
    "moderation.log_level": "INFO",
    "radio.max_members": 12,
    "server.maintenance_message": "Scheduled maintenance",
}


class ConfigError(Exception):
    """An invalid setting value, permission check, or version condition."""


class VersionConflict(ConfigError):
    """The config revision changed since the caller last read it."""


@dataclass(frozen=True)
class Actor:
    name: str
    staff: bool = False


def validate_setting(key: str, value: object) -> None:
    """Only permit explicitly declared, non-secret demo settings."""
    if key not in DEFAULTS:
        raise ConfigError("Unknown or restricted setting")
    expected = DEFAULTS[key]
    if type(value) is not type(expected):
        raise ConfigError("Setting type mismatch")
    if key == "support.max_open_tickets" and not 1 <= value <= 100:
        raise ConfigError("Ticket limit out of range (1–100)")
    if key == "radio.max_members" and not 2 <= value <= 99:
        raise ConfigError("Radio limit out of range (2–99)")
    if key == "moderation.log_level" and value not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigError("Unsupported logging level")
    if key == "server.maintenance_message" and not 1 <= len(value.strip()) <= 160:
        raise ConfigError("Maintenance message must be 1–160 nonblank characters")


class ConfigStore:
    """Versioned state and append-only audit with atomic multi-key updates."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("Use a file-backed SQLite database")
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    version INTEGER NOT NULL CHECK(version > 0)
                );
                CREATE TABLE IF NOT EXISTS config_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL REFERENCES settings(key),
                    actor TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK(operation IN ('change','restore')),
                    old_json TEXT NOT NULL,
                    new_json TEXT NOT NULL,
                    from_version INTEGER NOT NULL,
                    to_version INTEGER NOT NULL,
                    at TEXT NOT NULL
                );
            """)
        self.initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connect() as db:
            for key, value in DEFAULTS.items():
                db.execute(
                    "INSERT OR IGNORE INTO settings(key,value_json,version) VALUES (?,?,1)",
                    (key, json.dumps(value)),
                )

    @staticmethod
    def _staff(actor: Actor) -> str:
        if not isinstance(actor, Actor) or not actor.staff:
            raise ConfigError("Staff permission required")
        if not isinstance(actor.name, str) or not 1 <= len(actor.name.strip()) <= 64:
            raise ConfigError("Invalid staff identity")
        return actor.name.strip()

    @staticmethod
    def _row(db: sqlite3.Connection, key: str) -> sqlite3.Row:
        if key not in DEFAULTS:
            raise ConfigError("Unknown or restricted setting")
        result = db.execute("SELECT key,value_json,version FROM settings WHERE key=?",
                            (key,)).fetchone()
        if result is None:
            raise ConfigError("Setting missing")
        return result

    @staticmethod
    def _public(row: sqlite3.Row) -> dict:
        return {"key": row["key"], "value": json.loads(row["value_json"]),
                "version": row["version"]}

    def get(self, key: str) -> dict:
        with self._connect() as db:
            return self._public(self._row(db, key))

    def list(self) -> list[dict]:
        with self._connect() as db:
            return [self._public(row) for row in db.execute(
                "SELECT key,value_json,version FROM settings ORDER BY key"
            )]

    @staticmethod
    def _version(value: object) -> int:
        if type(value) is not int or value < 1:
            raise ConfigError("Expected version must be a positive integer")
        return value

    @staticmethod
    def _audit(db: sqlite3.Connection, *, key: str, actor: str,
               operation: str, old: str, new: str, version: int) -> None:
        db.execute("""
            INSERT INTO config_audit
            (key,actor,operation,old_json,new_json,from_version,to_version,at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            key, actor, operation, old, new, version, version + 1,
            datetime.now(timezone.utc).isoformat(),
        ))

    def _update_locked(self, db: sqlite3.Connection, key: str, value: object,
                       expected_version: int, actor: str, operation="change") -> dict:
        row = self._row(db, key)
        if row["version"] != expected_version:
            raise VersionConflict(f"Stale version for {key}; refresh and retry")
        validate_setting(key, value)
        new_json = json.dumps(value, ensure_ascii=False)
        if row["value_json"] == new_json:
            return self._public(row)  # no audit event for a duplicate no-op
        db.execute(
            "UPDATE settings SET value_json=?,version=version+1 WHERE key=?",
            (new_json, key),
        )
        self._audit(db, key=key, actor=actor, operation=operation,
                    old=row["value_json"], new=new_json, version=row["version"])
        return self._public(self._row(db, key))

    def update(self, actor: Actor, key: str, value: object,
               expected_version: int) -> dict:
        principal = self._staff(actor)
        version = self._version(expected_version)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._update_locked(db, key, value, version, principal)

    def update_batch(
        self, actor: Actor, changes: Mapping[str, tuple[object, int]],
    ) -> list[dict]:
        principal = self._staff(actor)
        if not changes or len(changes) > len(DEFAULTS):
            raise ConfigError("Batch must contain 1–5 known settings")
        # Validate before locking, then compare all versions in one transaction.
        for key, (value, version) in changes.items():
            validate_setting(key, value)
            self._version(version)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, (_, version) in changes.items():
                row = self._row(db, key)
                if row["version"] != version:
                    raise VersionConflict(f"Stale version for {key}; batch cancelled")
            return [
                self._update_locked(db, key, value, version, principal)
                for key, (value, version) in sorted(changes.items())
            ]

    def restore_previous(self, actor: Actor, key: str, expected_version: int) -> dict:
        principal = self._staff(actor)
        version = self._version(expected_version)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, key)
            if row["version"] != version:
                raise VersionConflict("Stale version; restore cancelled")
            previous = db.execute(
                "SELECT old_json FROM config_audit WHERE key=? ORDER BY id DESC LIMIT 1",
                (key,),
            ).fetchone()
            if previous is None:
                raise ConfigError("No previous value to restore")
            return self._update_locked(
                db, key, json.loads(previous["old_json"]), version,
                principal, operation="restore",
            )

    def history(self, key: str) -> list[dict]:
        if key not in DEFAULTS:
            raise ConfigError("Unknown or restricted setting")
        with self._connect() as db:
            return [
                {
                    "id": row["id"], "actor": row["actor"],
                    "operation": row["operation"],
                    "old_value": json.loads(row["old_json"]),
                    "new_value": json.loads(row["new_json"]),
                    "from_version": row["from_version"],
                    "to_version": row["to_version"],
                    "at": row["at"],
                }
                for row in db.execute(
                    "SELECT * FROM config_audit WHERE key=? ORDER BY id", (key,),
                )
            ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Local synthetic versioned settings")
    parser.add_argument("--db", default="demo-config.sqlite3")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list")
    get = actions.add_parser("get")
    get.add_argument("key")
    change = actions.add_parser("set")
    change.add_argument("key")
    change.add_argument("json_value", help='JSON literal, e.g. 12 or "WARNING"')
    change.add_argument("--version", type=int, required=True)
    change.add_argument("--actor", default="local-demo-admin")
    restore = actions.add_parser("restore")
    restore.add_argument("key")
    restore.add_argument("--version", type=int, required=True)
    restore.add_argument("--actor", default="local-demo-admin")
    history = actions.add_parser("history")
    history.add_argument("key")
    args = parser.parse_args()
    store = ConfigStore(args.db)
    try:
        if args.action == "list":
            output = store.list()
        elif args.action == "get":
            output = store.get(args.key)
        elif args.action == "set":
            output = store.update(
                Actor(args.actor, True), args.key, json.loads(args.json_value),
                args.version,
            )
        elif args.action == "restore":
            output = store.restore_previous(
                Actor(args.actor, True), args.key, args.version,
            )
        else:
            output = store.history(args.key)
    except (ConfigError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
