"""Tests for the independent, synthetic versioned-config backend."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from config_demo import Actor, ConfigError, ConfigStore, VersionConflict


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "demo.sqlite3"
        self.store = ConfigStore(self.path)
        self.admin = Actor("test-staff", True)
        self.user = Actor("test-user")

    def test_default_keys(self):
        self.assertEqual(len(self.store.list()), 5)

    def test_initial_version(self):
        self.assertEqual(self.store.get("support.max_open_tickets")["version"], 1)

    def test_initial_bool(self):
        self.assertTrue(self.store.get("support.allow_attachments")["value"])

    def test_get_unknown_key(self):
        with self.assertRaises(ConfigError):
            self.store.get("discord.token")

    def test_nonstaff_cannot_write(self):
        with self.assertRaisesRegex(ConfigError, "Staff"):
            self.store.update(self.user, "support.max_open_tickets", 12, 1)

    def test_invalid_staff_name(self):
        with self.assertRaises(ConfigError):
            self.store.update(Actor(" ", True), "support.max_open_tickets", 12, 1)

    def test_valid_change_creates_version_and_audit(self):
        result = self.store.update(self.admin, "support.max_open_tickets", 12, 1)
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["value"], 12)
        history = self.store.history("support.max_open_tickets")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_value"], 8)
        self.assertEqual(history[0]["new_value"], 12)
        self.assertEqual(history[0]["actor"], "test-staff")

    def test_repeat_same_value_no_new_audit(self):
        self.store.update(self.admin, "support.max_open_tickets", 8, 1)
        self.assertEqual(self.store.get("support.max_open_tickets")["version"], 1)
        self.assertEqual(self.store.history("support.max_open_tickets"), [])

    def test_repeat_after_change_same_version_noop(self):
        self.store.update(self.admin, "support.max_open_tickets", 12, 1)
        self.store.update(self.admin, "support.max_open_tickets", 12, 2)
        self.assertEqual(self.store.get("support.max_open_tickets")["version"], 2)
        self.assertEqual(len(self.store.history("support.max_open_tickets")), 1)

    def test_stale_version_refused(self):
        self.store.update(self.admin, "support.max_open_tickets", 12, 1)
        with self.assertRaises(VersionConflict):
            self.store.update(self.admin, "support.max_open_tickets", 20, 1)
        self.assertEqual(self.store.get("support.max_open_tickets")["value"], 12)

    def test_bool_cannot_replace_integer(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "support.max_open_tickets", True, 1)

    def test_integer_cannot_replace_bool(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "support.allow_attachments", 1, 1)

    def test_ticket_limit_lower_bound(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "support.max_open_tickets", 0, 1)

    def test_ticket_limit_upper_bound(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "support.max_open_tickets", 101, 1)

    def test_radio_limit_lower_bound(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "radio.max_members", 1, 1)

    def test_log_level_enumeration(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "moderation.log_level", "TRACE", 1)

    def test_valid_log_level(self):
        result = self.store.update(self.admin, "moderation.log_level", "ERROR", 1)
        self.assertEqual(result["value"], "ERROR")

    def test_maintenance_message_blank(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "server.maintenance_message", "  ", 1)

    def test_maintenance_message_too_long(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "server.maintenance_message", "A" * 161, 1)

    def test_unknown_restricted_key_cannot_be_inserted(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "discord.bot_token", "fake", 1)
        self.assertEqual(len(self.store.list()), 5)

    def test_expected_version_type(self):
        with self.assertRaises(ConfigError):
            self.store.update(self.admin, "support.max_open_tickets", 12, True)

    def test_batch_updates_both(self):
        results = self.store.update_batch(self.admin, {
            "radio.max_members": (20, 1),
            "support.max_open_tickets": (16, 1),
        })
        self.assertEqual(len(results), 2)
        self.assertEqual(self.store.get("radio.max_members")["value"], 20)
        self.assertEqual(self.store.get("support.max_open_tickets")["version"], 2)

    def test_batch_stale_second_rolls_back_first(self):
        self.store.update(self.admin, "support.max_open_tickets", 15, 1)
        with self.assertRaises(VersionConflict):
            self.store.update_batch(self.admin, {
                "radio.max_members": (30, 1),
                "support.max_open_tickets": (16, 1),
            })
        self.assertEqual(self.store.get("radio.max_members")["version"], 1)
        self.assertEqual(self.store.get("radio.max_members")["value"], 12)

    def test_batch_invalid_value_rolls_back_all(self):
        with self.assertRaises(ConfigError):
            self.store.update_batch(self.admin, {
                "radio.max_members": (25, 1),
                "support.max_open_tickets": (900, 1),
            })
        self.assertEqual(self.store.get("radio.max_members")["version"], 1)

    def test_batch_nonstaff_denied(self):
        with self.assertRaises(ConfigError):
            self.store.update_batch(self.user, {"radio.max_members": (30, 1)})

    def test_batch_empty_denied(self):
        with self.assertRaises(ConfigError):
            self.store.update_batch(self.admin, {})

    def test_restore_previous_value(self):
        self.store.update(self.admin, "radio.max_members", 21, 1)
        state = self.store.restore_previous(self.admin, "radio.max_members", 2)
        self.assertEqual(state["value"], 12)
        self.assertEqual(state["version"], 3)
        history = self.store.history("radio.max_members")
        self.assertEqual([x["operation"] for x in history], ["change", "restore"])

    def test_restore_without_history_fails(self):
        with self.assertRaises(ConfigError):
            self.store.restore_previous(self.admin, "radio.max_members", 1)

    def test_restore_wrong_version_fails(self):
        self.store.update(self.admin, "radio.max_members", 21, 1)
        with self.assertRaises(VersionConflict):
            self.store.restore_previous(self.admin, "radio.max_members", 1)
        self.assertEqual(self.store.get("radio.max_members")["value"], 21)

    def test_restore_permission_denied(self):
        self.store.update(self.admin, "radio.max_members", 21, 1)
        with self.assertRaises(ConfigError):
            self.store.restore_previous(self.user, "radio.max_members", 2)

    def test_read_after_reopen(self):
        self.store.update(self.admin, "radio.max_members", 21, 1)
        self.assertEqual(ConfigStore(self.path).get("radio.max_members")["value"], 21)

    def test_initialize_does_not_reset_changes(self):
        self.store.update(self.admin, "radio.max_members", 21, 1)
        self.store.initialize()
        self.assertEqual(self.store.get("radio.max_members")["version"], 2)

    def test_sql_content_is_ordinary_string(self):
        value = "Display: '; DROP TABLE settings; --"
        self.store.update(self.admin, "server.maintenance_message", value, 1)
        self.assertEqual(self.store.get("server.maintenance_message")["value"], value)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM settings").fetchone()[0], 5)

    def test_concurrent_expected_version_writes_one_wins(self):
        def update(value):
            try:
                return self.store.update(self.admin, "radio.max_members", value, 1)
            except VersionConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(update, (24, 26)))
        self.assertEqual(sum(x is not None for x in outcomes), 1)
        self.assertEqual(self.store.get("radio.max_members")["version"], 2)

    def test_command_line_demo_list(self):
        result = subprocess.run(
            [sys.executable, "config_demo.py", "--db", str(self.path), "list"],
            capture_output=True, text=True, check=True,
        )
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 5)

    def test_no_hardcoded_secrets_in_allowed_keys(self):
        self.assertNotIn("token", " ".join(x["key"] for x in self.store.list()))
        self.assertNotIn("password", " ".join(x["key"] for x in self.store.list()))


if __name__ == "__main__":
    unittest.main()
