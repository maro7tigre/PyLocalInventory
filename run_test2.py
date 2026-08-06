import unittest
import sys
import tests.test_recent_changes_full

suite = unittest.TestSuite()
suite.addTest(tests.test_recent_changes_full.TestBaseOperationDialogAsync("test_save_worker_success"))
runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
runner.run(suite)
