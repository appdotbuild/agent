import uvicorn
import argparse
import logging
import sys
import os

# Add parent directory to path to enable imports
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(parent_dir)

if __name__ == "__main__":
    # Configure argument parser
    parser = argparse.ArgumentParser(description="Run the Agent Server API")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
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
    
    # Run the server
    uvicorn.run(
        "api.agent_server.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level
    )