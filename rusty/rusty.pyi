from typing import Optional

class Config:
    """Configuration singleton that provides access to environment variables."""
    
    def __new__(cls) -> 'Config': ...
    
    @staticmethod
    def instance() -> 'Config': ...
    
    @property
    def agent_type(self) -> str: ...
    
    @property
    def builder_token(self) -> Optional[str]: ...
    
    @property
    def snapshot_bucket(self) -> Optional[str]: ...

# Singleton instance
CONFIG: Config