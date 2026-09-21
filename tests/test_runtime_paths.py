import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_paths


class RuntimeResourcePathTests(unittest.TestCase):
    def test_source_mode_resolves_from_project_root_not_working_directory(self):
        expected = Path(runtime_paths.__file__).resolve().parents[1] / "report" / "devis_templet.html"
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as other_directory:
            try:
                os.chdir(other_directory)
                actual = Path(runtime_paths.resource_path("report", "devis_templet.html"))
            finally:
                os.chdir(original_cwd)
        self.assertEqual(actual, expected)

    def test_frozen_mode_resolves_from_pyinstaller_meipass(self):
        with tempfile.TemporaryDirectory() as bundle_directory:
            with patch.object(sys, "frozen", True, create=True), \
                    patch.object(sys, "_MEIPASS", bundle_directory, create=True):
                actual = Path(runtime_paths.resource_path("report", "lamidap_logo.png"))
        self.assertEqual(
            actual,
            Path(bundle_directory).resolve() / "report" / "lamidap_logo.png",
        )


if __name__ == "__main__":
    unittest.main()
