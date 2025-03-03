import os
import uvicorn

import logging
import logging.handlers
from datetime import datetime
import sys

logger = logging.getLogger(__name__)


# configure logging with time, file, line number and write to console and rotated files
def setup_logging():
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    
    log_dir = os.path.join(os.getcwd(), '/tmp/logs')
    os.makedirs(log_dir, exist_ok=True)
    
    file_handler = logging.handlers.RotatingFileHandler(
        filename=os.path.join(log_dir, f'server_{datetime.now().strftime("%Y%m%d")}.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    file_handler.setFormatter(log_formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('anthropic').setLevel(logging.INFO)

setup_logging()


def start_app() -> None:
    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8080")),
        access_log=False,
        reload=os.getenv("RELOAD", "false").lower() == "true",
        timeout_keep_alive=60 * 20 * 1000, # 20 minutes
    )


if __name__ == "__main__":
    start_app()
