import os
import tempfile
import unittest
import io
import zipfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QDialog, QWidget

from classes.client_class import ClientClass
from core import pg_backup
from core.network.client import RemoteDatabase as NetworkRemoteDatabase
from core.network.server import _check_permission
from ui.dialogs.client_details_dialog import ClientDetailsDialog
from ui.dialogs.backups_dialog import BackupsDialog


def _user(client_read=False, client_write=False, sales_write=False):
    return {
        "is_superadmin": False,
        "permissions": {
            "Clients": {
                "read": client_read,
                "write": client_write,
                "delete": False,
            },
            "Sales": {"read": False, "write": sales_write, "delete": False},
            "Reports": {"read": True, "write": False, "delete": False},
        },
    }


class RemoteDatabase:
    def __init__(self, can_record_payment=False):
        self.can_record_payment = can_record_payment
        self.account_calls = []

    def has_permission(self, section, action="read"):
        return (
            (section == "Clients" and action == "read")
            or (section == "Sales" and action == "write" and self.can_record_payment)
        )

    def get_client_account(self, client_id):
        self.account_calls.append(client_id)
        return {"purchases": [], "payments": []}


class ClientPermissionAndBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_client_account_rpc_requires_only_clients_read(self):
        allowed, _ = _check_permission(_user(client_read=True), "get_client_account", [7], {})
        self.assertTrue(allowed)
        allowed, _ = _check_permission(_user(client_read=True), "get_client_sales", [7], {})
        self.assertTrue(allowed)
        denied, _ = _check_permission(_user(), "get_client_account", [7], {})
        self.assertFalse(denied)

    def test_client_payment_rpc_requires_clients_read_and_sales_write(self):
        denied, _ = _check_permission(
            _user(client_read=True), "add_client_payment", [7, 8, 9, 10, "2026-07-27"], {}
        )
        self.assertFalse(denied)
        allowed, _ = _check_permission(
            _user(client_read=True, sales_write=True),
            "add_client_payment",
            [7, 8, 9, 10, "2026-07-27"],
            {},
        )
        self.assertTrue(allowed)

    def test_regular_user_cannot_bypass_report_ownership_with_raw_sql(self):
        allowed, reason = _check_permission(
            _user(client_read=True),
            "cursor.execute",
            ["SELECT * FROM Reports WHERE id = %s", [77]],
            {},
        )
        self.assertFalse(allowed)
        self.assertIn("ownership-filtered", reason)

    def test_sale_attachment_download_allowed_with_sales_read(self):
        user = {
            "is_superadmin": False,
            "permissions": {
                "Clients": {"read": False, "write": False, "delete": False},
                "Sales": {"read": True, "write": False, "delete": False},
                "Reports": {"read": True, "write": False, "delete": False},
            },
        }
        allowed, _ = _check_permission(user, "download_attachment", [42], {})
        self.assertTrue(allowed)

    def test_read_only_client_dialog_loads_and_hides_payment_controls(self):
        database = RemoteDatabase(can_record_payment=False)
        client = ClientClass(7, database)
        client.set_value("id", 7)
        client.set_value("name", "Read Only Client")
        dialog = ClientDetailsDialog(client, database)
        self.assertEqual(database.account_calls, [7])
        self.assertTrue(dialog.payment_form.isHidden())
        self.assertFalse(dialog.can_record_payment)
        dialog.close()

    def test_backup_creation_needs_pg_dump_but_not_pg_restore(self):
        config = {
            "host": "db host",
            "port": 5432,
            "user": "inventory",
            "password": "secret",
        }

        def completed(command, **kwargs):
            output = command[command.index("--file") + 1]
            with open(output, "wb") as stream:
                stream.write(b"PGDMP-test")
            self.assertNotIn("secret", command)
            self.assertFalse(kwargs["shell"])
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with tempfile.TemporaryDirectory() as directory, patch(
            "core.pg_backup.load_server_config", return_value=config
        ), patch(
            "core.pg_backup._require_tool", return_value=r"C:\PostgreSQL\bin\pg_dump.exe"
        ) as require_tool, patch("core.pg_backup.subprocess.run", side_effect=completed):
            output = pg_backup.backup_database("inventory db", directory)

        require_tool.assert_called_once_with("pg_dump", config)
        self.assertTrue(os.path.basename(output).startswith("inventory_db_"))
        self.assertTrue(output.endswith(".backup"))

    def test_profile_attachment_folder_is_copied_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_dir = os.path.join(directory, "profile")
            backups_dir = os.path.join(profile_dir, "backups")
            attachments_dir = os.path.join(profile_dir, "attachments")
            os.makedirs(backups_dir)
            os.makedirs(attachments_dir)
            with open(os.path.join(profile_dir, "config.json"), "w", encoding="utf-8") as stream:
                stream.write("{}")
            with open(os.path.join(attachments_dir, "document.pdf"), "wb") as stream:
                stream.write(b"%PDF-test")

            parent = QWidget()
            parent.database = object()
            dialog = BackupsDialog.__new__(BackupsDialog)
            QDialog.__init__(dialog, parent)
            dialog.profile_dir = profile_dir
            dialog.backups_dir = backups_dir
            dialog._backup_running = False
            dialog.current_profile = type(
                "Profile", (), {"database_name": "inventory", "schema_name": None}
            )()

            def fake_database_backup(_database_name, destination):
                with open(os.path.join(destination, "database.backup"), "wb") as stream:
                    stream.write(b"PGDMP-test")

            with patch(
                "ui.dialogs.backups_dialog.pg_backup.backup_database",
                side_effect=fake_database_backup,
            ), patch(
                "ui.dialogs.backups_dialog.attachment_backup_root",
                return_value=__import__("pathlib").Path(attachments_dir),
            ):
                self.assertTrue(dialog.create_backup("safe", show_errors=False))

            copied = os.path.join(
                backups_dir, "safe", "attachments", "document.pdf"
            )
            self.assertTrue(os.path.isfile(copied))
            dialog.close()
            parent.close()

    def test_network_client_backup_does_not_require_local_profile(self):
        parent = QWidget()
        parent.profile_manager = type(
            "ProfileManager", (), {"selected_profile": None}
        )()
        parent.database = type(
            "RemoteBackupDatabase", (), {"download_backup": lambda *_args: None}
        )()
        dialog = BackupsDialog(parent)
        self.assertTrue(dialog.remote_mode)
        self.assertTrue(dialog.download_btn.isEnabled())
        dialog.close()
        parent.close()

    def test_network_backup_download_is_validated_and_atomically_saved(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("database/test.backup", b"PGDMP-test")
        data = payload.getvalue()

        class Response:
            status = 200

            def __init__(self):
                self.offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, size=-1):
                if self.offset >= len(data):
                    return b""
                end = len(data) if size < 0 else min(len(data), self.offset + size)
                chunk = data[self.offset:end]
                self.offset = end
                return chunk

        remote = NetworkRemoteDatabase(None, "host-pc", 8765, "admin", "secret")
        remote._token = "test-token"
        with tempfile.TemporaryDirectory() as directory:
            destination = os.path.join(directory, "shared.zip")
            with patch("urllib.request.urlopen", return_value=Response()):
                result = remote.download_backup(destination)
            self.assertEqual(result, destination)
            self.assertTrue(zipfile.is_zipfile(destination))
            self.assertFalse(os.path.exists(destination + ".part"))


if __name__ == "__main__":
    unittest.main()
