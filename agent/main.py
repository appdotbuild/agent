import os
import uvicorn
import sys
from datetime import datetime
import logging
import logging.handlers
from common import get_logger

logger = get_logger(__name__)

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
