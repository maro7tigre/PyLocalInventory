import logging
import os
import unittest
import uuid

from core.logging_config import setup_logging


class LoggingConfigTests(unittest.TestCase):
    def test_application_log_is_created_and_writable(self):
        path = setup_logging()
        token = f"logging-test-{uuid.uuid4()}"
        logging.getLogger("tests.logging").error(token)
        for handler in logging.getLogger().handlers:
            handler.flush()

        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.basename(path), "app.log")
        with open(path, encoding="utf-8") as stream:
            self.assertIn(token, stream.read())


if __name__ == "__main__":
    unittest.main()
