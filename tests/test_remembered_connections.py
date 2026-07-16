import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core import user_settings
from ui.widgets.login_widget import LoginWidget, NetworkUnlockWidget


class RememberedConnectionSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "settings.json")
        self.path_patch = patch.object(user_settings, "settings_path", return_value=self.path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_network_connection_contains_no_password_and_selects_network_mode(self):
        settings = user_settings.set_remembered_network({}, "host.local", 8765, "alice")
        self.assertEqual(settings["startup_mode"], "network_client")
        self.assertNotIn("password", json.dumps(settings).lower())
        self.assertEqual(user_settings.get_remembered_network(settings)["username"], "alice")

    def test_local_and_network_modes_are_distinct(self):
        settings = user_settings.set_remembered_network({}, "10.0.0.2", 8765, "bob")
        settings = user_settings.set_remembered_profile(settings, "Warehouse")
        self.assertTrue(user_settings.remember_profile_enabled(settings))
        self.assertEqual(user_settings.get_remembered_network(settings), {})

    def test_corrupt_network_state_falls_back_safely(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"startup_mode": "network_client", "remember_network_connection": True,
                       "remembered_network": {"host": "x", "port": "bad", "username": "u"}}, handle)
        settings = user_settings.load_settings()
        self.assertEqual(settings["startup_mode"], "none")
        self.assertEqual(settings["remembered_network"], {})

    def test_legacy_local_settings_are_migrated(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"remember_profile": True, "remembered_profile_id": "Legacy"}, handle)
        settings = user_settings.load_settings()
        self.assertEqual(settings["startup_mode"], "local_profile")


class RememberedConnectionWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_full_form_prefills_saved_values_without_password(self):
        widget = LoginWidget("server", "9000", "alice", True, True)
        self.assertEqual(widget.host_input.text(), "server")
        self.assertEqual(widget.port_input.text(), "9000")
        self.assertEqual(widget.username_input.text(), "alice")
        self.assertEqual(widget.password_input.text(), "")
        self.assertTrue(widget.remember_checkbox.isChecked())
        self.assertTrue(widget.startup_checkbox.isChecked())

    def test_unlock_shows_connection_and_clears_failed_password(self):
        widget = NetworkUnlockWidget({"host": "server", "port": 8765, "username": "alice"}, True)
        widget.password_input.setText("secret")
        widget.set_error("Unable to reach host")
        widget.clear_password()
        self.assertEqual(widget.password_input.text(), "")
        self.assertEqual(widget.error_label.text(), "Unable to reach host")


if __name__ == "__main__":
    unittest.main()
