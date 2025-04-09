import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from server import get_handler_app
from api.agent_server.empty_diff_impl import EmptyDiffAgentImplementation


logger = logging.getLogger(__name__)


print("IN MAIN")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Async Agent Server API")
    yield
    logger.info("Shutting down Async Agent Server API")


app = FastAPI(
    title="Async Agent Server API",
    description="Async API for communication between the Platform (Backend) and the Agent Server",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/healthcheck")
async def healthcheck():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {"status": "healthy"}


app.mount("/message", get_handler_app(EmptyDiffAgentImplementation))


if __name__ == "__main__":
    print("IN MAIN __name__")
    import uvicorn
    import argparse
    import sys
    import os
    
    # Add parent directory to path to enable imports
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.append(parent_dir)
    
    # Configure argument parser
    parser = argparse.ArgumentParser(description="Run the Async Agent Server API")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="info", 
                      choices=["debug", "info", "warning", "error", "critical"],
                      help="Logging level")
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = getattr(logging, args.log_level.upper())
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info(f"Starting server on {args.host}:{args.port} with log level {args.log_level}")
    
    # Run the server
    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level
    )
