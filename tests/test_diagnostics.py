from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        diagnostics.close_logging()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.addCleanup(diagnostics.close_logging)
        self.log_path = Path(self.temp_directory.name) / "logs" / "windows-ddc.log"

    def test_component_message_is_written_to_the_requested_path(self) -> None:
        diagnostics.configure_logging(self.log_path)

        diagnostics.get_logger("tests.component").info("safe diagnostic")
        diagnostics.close_logging()

        contents = self.log_path.read_text(encoding="utf-8")
        self.assertIn(" INFO MainThread windows_ddc.component safe diagnostic", contents)

    def test_configuration_is_idempotent(self) -> None:
        diagnostics.configure_logging(self.log_path)
        diagnostics.configure_logging(self.log_path)

        diagnostics.get_logger("test").warning("one message")
        diagnostics.close_logging()

        contents = self.log_path.read_text(encoding="utf-8")
        self.assertEqual(contents.count("one message"), 1)

    def test_log_rotates_with_bounded_backups(self) -> None:
        with patch.object(diagnostics, "LOG_MAX_BYTES", 128), patch.object(
            diagnostics,
            "LOG_BACKUP_COUNT",
            2,
        ):
            diagnostics.configure_logging(self.log_path)
            logger = diagnostics.get_logger("rotation")
            for index in range(20):
                logger.info("rotation message %02d with padding", index)
            diagnostics.close_logging()

        self.assertTrue(Path(f"{self.log_path}.1").is_file())
        self.assertTrue(Path(f"{self.log_path}.2").is_file())
        self.assertFalse(Path(f"{self.log_path}.3").exists())

    def test_handler_setup_failure_is_nonfatal(self) -> None:
        with patch("diagnostics.RotatingFileHandler", side_effect=OSError("denied")):
            logger = diagnostics.configure_logging(self.log_path)
            logger.error("discarded diagnostic")

        diagnostics.close_logging()
        self.assertFalse(self.log_path.exists())

    def test_handler_close_failure_is_nonfatal_and_removes_the_handler(self) -> None:
        handler = Mock()
        setattr(handler, diagnostics._HANDLER_MARKER, True)
        handler.close.side_effect = OSError("close failed")
        diagnostics._BASE_LOGGER.addHandler(handler)

        diagnostics.close_logging()

        self.assertNotIn(handler, diagnostics._BASE_LOGGER.handlers)


if __name__ == "__main__":
    unittest.main()
