import os
from typing import Optional

def get_template_path(file_path: Optional[str] = None) -> str:
    """
    Get the absolute path to the trpc_agent/template directory.
    
    Args:
        file_path: Optional file path to use as reference. If not provided, 
                  uses the current file's location.
    
    Returns:
        Absolute path to the trpc_agent/template directory.
    """
    if file_path is None:
        file_path = __file__
    
    if "trpc_agent" in os.path.dirname(file_path):
        return os.path.abspath(
            os.path.join(os.path.dirname(file_path), "../template")
        )
    
    return os.path.abspath(
        os.path.join(os.path.dirname(file_path), "../../trpc_agent/template")
    )
