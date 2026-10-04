import json
import logging

from app.core.logging import JsonFormatter, configure_logging


def test_json_formatter_returns_structured_log() -> None:
    record = logging.LogRecord(
        name="agenthire.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="test_event",
        args=(),
        exc_info=None,
    )

    formatted_log = JsonFormatter().format(record)
    log_data = json.loads(formatted_log)

    assert log_data["level"] == "INFO"
    assert log_data["logger"] == "agenthire.test"
    assert log_data["message"] == "test_event"
    assert "timestamp" in log_data


def test_configure_logging_configures_agenthire_logger() -> None:
    configure_logging(level="DEBUG")

    logger = logging.getLogger("agenthire")

    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, JsonFormatter)
    assert logger.propagate is False
