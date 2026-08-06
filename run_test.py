import traceback
import sys
import tests.test_recent_changes_full as t

try:
    c = t.TestBaseOperationDialogAsync('test_save_worker_success')
    c.setUp()
    c.test_save_worker_success()
except Exception as e:
    traceback.print_exc(file=sys.stdout)
