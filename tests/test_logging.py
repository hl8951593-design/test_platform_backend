import io
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from app.core import logging as logging_config


class LoggingConfigurationTests(unittest.TestCase):
    def test_locked_windows_rollover_is_deferred_without_logging_error(self):
        handler_class = getattr(
            logging_config,
            "WindowsSafeRotatingFileHandler",
            None,
        )
        if handler_class is None:
            self.fail("File logging must use a Windows-safe rotating handler")

        logger = logging.getLogger("tests.logging.locked_rollover")
        original_handlers = list(logger.handlers)
        original_level = logger.level
        original_propagate = logger.propagate

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "app.log"
            handler = handler_class(
                log_path,
                maxBytes=1,
                backupCount=1,
                encoding="utf-8",
                rollover_defer_seconds=60.0,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))

            logger.handlers = [handler]
            logger.setLevel(logging.INFO)
            logger.propagate = False

            stderr = io.StringIO()
            locked_error = PermissionError(13, "file is locked")
            locked_error.winerror = 32
            with (
                redirect_stderr(stderr),
                patch.object(os, "rename", side_effect=locked_error) as rename,
            ):
                logger.info("first message")
                logger.info("second message")

            handler.flush()
            handler.close()

            self.assertNotIn("--- Logging error ---", stderr.getvalue())
            self.assertEqual(rename.call_count, 1)
            self.assertIn("first message", log_path.read_text(encoding="utf-8"))
            self.assertIn("second message", log_path.read_text(encoding="utf-8"))

        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate

    def test_configure_logging_uses_windows_safe_file_handler(self):
        handler_class = getattr(
            logging_config,
            "WindowsSafeRotatingFileHandler",
            None,
        )
        if handler_class is None:
            self.fail("configure_logging must install the Windows-safe handler")

        root_logger = logging.getLogger()
        original_handlers = list(root_logger.handlers)
        original_level = root_logger.level
        had_configured_flag = hasattr(root_logger, "_test_platform_configured")
        original_configured_flag = getattr(root_logger, "_test_platform_configured", None)

        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)

        if had_configured_flag:
            delattr(root_logger, "_test_platform_configured")

        temp_dir = tempfile.TemporaryDirectory()
        try:
            log_path = Path(temp_dir.name) / "app.log"
            with patch.object(logging_config.settings, "LOG_FILE_PATH", str(log_path)):
                logging_config.configure_logging()

            self.assertTrue(
                any(
                    isinstance(handler, handler_class)
                    for handler in root_logger.handlers
                )
            )
        finally:
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                handler.close()
            for handler in original_handlers:
                root_logger.addHandler(handler)
            root_logger.setLevel(original_level)
            if had_configured_flag:
                root_logger._test_platform_configured = original_configured_flag
            elif hasattr(root_logger, "_test_platform_configured"):
                delattr(root_logger, "_test_platform_configured")
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
