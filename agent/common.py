import watchtower
import logging
import logging.handlers
import logging.config
import sentry_sdk
import os
import boto3
from datetime import datetime
from botocore.exceptions import NoCredentialsError, ClientError

# Configure root logger to avoid duplicate handlers
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)

# Single formatter definition
_FORMATTER = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
)


def _init_logging():
    handlers = {}

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(_FORMATTER)
    handlers['console'] = console

    # CloudWatch handler
    try:
        session = boto3.Session()
        # for local dev, it would require using boto3.Session(profile_name="dev")
        cli = session.client("logs", region_name=os.getenv("AWS_REGION", "us-west-2"))
        cloudwatch = watchtower.CloudWatchLogHandler(
            log_group_name="codegen-logs",
            boto3_client=cli,
            log_stream_name="{machine_name}_{strftime:%m-%d-%y}",
            use_queues=False,  # this is not performant, but otherwise race conditions occur on uvicorn level
        )
        cloudwatch.setFormatter(_FORMATTER)
        handlers['cloudwatch'] = cloudwatch
    except NoCredentialsError:
        logging.warning("CloudWatch credentials not found")
    except Exception as e:
        logging.exception("CloudWatch logging disabled")

    # File handler
    if log_dir := os.getenv("LOG_DIR", ""):
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(log_dir, f'server_{datetime.now().strftime("%Y%m%d")}.log'),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        file_handler.setFormatter(_FORMATTER)
        handlers['file'] = file_handler

    # Configure the root logger with these handlers
    for handler in handlers.values():
        if handler is not None:
            root_logger.addHandler(handler)

    root_logger.setLevel(logging.INFO)

    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('anthropic').setLevel(logging.INFO)

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
        # Send a test event to verify Sentry is working
        try:
            logger.info("Sending test event to Sentry")
            sentry_sdk.capture_message("Sentry initialization test")
            sentry_sdk.capture_event({"message": "Sentry initialization test as event"})

        except Exception as e:
            logger.exception("Failed to send test event to Sentry")
    else:
        logger.warning("Sentry disabled")
