from typing import Optional

class Config:
    @property
    def agent_type(self) -> str: ...
    
    @property
    def builder_token(self) -> Optional[str]: ...