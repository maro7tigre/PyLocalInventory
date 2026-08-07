import sys
sys.path.insert(0, '.')
import unittest
from tests.test_save_stability import TestSaveStability
from unittest.mock import patch

with patch('PySide6.QtWidgets.QMessageBox.information', return_value=None), \
     patch('PySide6.QtWidgets.QMessageBox.warning', return_value=None), \
     patch('PySide6.QtWidgets.QMessageBox.critical', return_value=None):
    suite = unittest.TestSuite()
    suite.addTest(TestSaveStability('test_duplicate_save_protection'))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
