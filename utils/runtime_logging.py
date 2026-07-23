from __future__ import annotations

import logging
import sys
import threading
import warnings
from datetime import datetime
from pathlib import Path


class _LevelFilter(logging.Filter):
    def __init__(self, min_level: int) -> None:
        super().__init__()
        self._min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self._min_level


class _StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int, fallback_stream) -> None:
        self._logger = logger
        self._level = level
        self._fallback_stream = fallback_stream
        self._buffer = ""
        self.encoding = getattr(fallback_stream, "encoding", "utf-8")
        self.errors = getattr(fallback_stream, "errors", "replace")

    def write(self, message) -> int:
        if not message:
            return 0

        if isinstance(message, bytes):
            message = message.decode(self.encoding or "utf-8", errors=self.errors or "replace")
        elif not isinstance(message, str):
            message = str(message)

        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(message)

    def flush(self) -> None:
        if self._buffer:
            self._emit(self._buffer)
            self._buffer = ""
        if hasattr(self._fallback_stream, "flush"):
            self._fallback_stream.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._fallback_stream, "isatty", lambda: False)())

    def fileno(self) -> int:
        if hasattr(self._fallback_stream, "fileno"):
            return self._fallback_stream.fileno()
        raise OSError("Stream does not expose a file descriptor")

    def _emit(self, line: str) -> None:
        text = line.rstrip()
        if text:
            self._logger.log(self._level, text)


def setup_runtime_logging(app_name: str, logs_dir: str = "logs") -> dict[str, str]:
    current_key = getattr(setup_runtime_logging, "_configured_key", None)
    if current_key == app_name:
        return getattr(setup_runtime_logging, "_configured_paths")

    log_root = Path(logs_dir)
    log_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_log = log_root / f"{app_name}.{timestamp}.log"
    session_error_log = log_root / f"{app_name}.{timestamp}.error.log"
    latest_log = log_root / f"{app_name}.latest.log"
    latest_error_log = log_root / f"{app_name}.latest.error.log"

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    handler_specs = [
        logging.FileHandler(session_log, mode="a", encoding="utf-8"),
        logging.FileHandler(latest_log, mode="w", encoding="utf-8"),
        logging.FileHandler(session_error_log, mode="a", encoding="utf-8"),
        logging.FileHandler(latest_error_log, mode="w", encoding="utf-8"),
        logging.StreamHandler(original_stdout),
    ]

    for handler in handler_specs:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    root_logger.handlers[2].setLevel(logging.ERROR)
    root_logger.handlers[2].addFilter(_LevelFilter(logging.ERROR))
    root_logger.handlers[3].setLevel(logging.ERROR)
    root_logger.handlers[3].addFilter(_LevelFilter(logging.ERROR))

    warnings_logger = logging.getLogger("py.warnings")
    warnings_logger.handlers.clear()
    warnings_logger.propagate = True
    logging.captureWarnings(True)

    def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            if original_stderr:
                original_stderr.write("KeyboardInterrupt\n")
                original_stderr.flush()
            return
        root_logger.exception(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = _log_unhandled_exception

    if hasattr(threading, "excepthook"):
        def _thread_excepthook(args) -> None:
            _log_unhandled_exception(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = _thread_excepthook

    sys.stdout = _StreamToLogger(logging.getLogger(f"{app_name}.stdout"), logging.INFO, original_stdout)
    sys.stderr = _StreamToLogger(logging.getLogger(f"{app_name}.stderr"), logging.ERROR, original_stderr)

    root_logger.info("Runtime logging initialized for %s", app_name)
    root_logger.info("Log file: %s", session_log.resolve())
    root_logger.info("Error log file: %s", session_error_log.resolve())

    paths = {
        "session_log": str(session_log),
        "session_error_log": str(session_error_log),
        "latest_log": str(latest_log),
        "latest_error_log": str(latest_error_log),
    }
    setattr(setup_runtime_logging, "_configured_key", app_name)
    setattr(setup_runtime_logging, "_configured_paths", paths)
    return paths
