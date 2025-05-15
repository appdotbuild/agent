"""
Global logging setup for the agent system.

Provides a centralized logging configuration used by various components
(Api, Core, TrpcAgent, LLM, Test Clients) as indicated in the architecture diagram.
"""
import logging
import logging.handlers
import logging.config
import json
import sentry_sdk
import os
import socket

# Configure root logger to avoid duplicate handlers
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)

# Check if running in ECS environment
def is_running_in_ecs() -> bool:
    return bool(os.getenv('ECS_CONTAINER_METADATA_URI') or
               os.getenv('AWS_EXECUTION_ENV', '').startswith('AWS_ECS'))

# JSON formatter for structured logging
class JsonFormatter(logging.Formatter):
    def __init__(self):
        super().__init__()
        self.hostname = socket.gethostname()

    def format(self, record) -> str:
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'file': record.filename,
            'line': record.lineno,
            'message': record.getMessage(),
            'hostname': self.hostname,
            "session_id": os.getenv("SESSION_ID", "default"),
        }

        # Add exception info if available
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)

# Standard text formatter
_TEXT_FORMATTER = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s'
)

# Choose formatter based on environment
_FORMATTER = JsonFormatter() if is_running_in_ecs() else _TEXT_FORMATTER


def _init_logging():
    handlers = {}

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(_FORMATTER)
    handlers['console'] = console

    # Configure the root logger with these handlers
    for handler in handlers.values():
        if handler is not None:
            root_logger.addHandler(handler)

    root_logger.setLevel(logging.INFO)

    # Set log levels for noisy loggers
    for package in ['urllib3', 'httpx', 'google_genai.models', "anthropic._base_client"]:
        logging.getLogger(package).setLevel(logging.WARNING)

    return handlers

# Initialize logging once at module import
_init_logging()


def get_logger(name):
    _logger = logging.getLogger(name)
    return _logger

logger = get_logger(__name__)

def init_sentry():
    sentry_dsn = os.getenv("SENTRY_DSN")

    if sentry_dsn:
        logger.info("Sentry enabled")
        sentry_sdk.init(
            dsn=sentry_dsn,
            # Add data like request headers and IP for users,
            # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
            send_default_pii=True,
            # Set traces_sample_rate to 1.0 to capture 100%
            # of transactions for tracing.
            traces_sample_rate=1.0,
            # Set profiles_sample_rate to 1.0 to profile 100%
            # of sampled transactions.
            # We recommend adjusting this value in production.
            profiles_sample_rate=1.0,
            environment=os.getenv("SENTRY_ENVIRONMENT", "dev"),
        )
    else:
        logger.warning("Sentry disabled")


def configure_uvicorn_logging():
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": _TEXT_FORMATTER._fmt,
            },
        },
        "loggers": {
            "uvicorn": {"level": "INFO", "propagate": True},
            "uvicorn.error": {"level": "INFO", "propagate": True},
            "uvicorn.access": {"level": "INFO", "propagate": True},
        },
    }

    return logging_config
