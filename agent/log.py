"""
Global logging setup for the agent system.

Provides a centralized logging configuration used by various components
(Api, Core, TrpcAgent, LLM, Test Clients) as indicated in the architecture diagram.
"""
import logging
import logging.handlers
import logging.config
import sentry_sdk
import os

# Configure root logger to avoid duplicate handlers
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)

# Single formatter definition
_FORMATTER = logging.Formatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s'
)


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
        
    # Set log levels for verbose state machine components
    for module in ['api.fsm_tools', 'core.statemachine']:
        logging.getLogger(module).setLevel(logging.WARNING)

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
                "format": _FORMATTER._fmt,
            },
        },
        "loggers": {
            "uvicorn": {"level": "INFO", "propagate": True},
            "uvicorn.error": {"level": "INFO", "propagate": True},
            "uvicorn.access": {"level": "INFO", "propagate": True},
        },
    }

    return logging_config
