"""Diff management for tracking and deduplicating diff operations."""

import logging
from typing import Dict, Optional

from trpc_agent.diff_utils import hash_diff

logger = logging.getLogger(__name__)


class DiffManager:
    """Manages diff state and deduplication logic."""
    
    def __init__(self):
        self._prev_diff_hash: Optional[str] = None
        self._template_diff_sent: bool = False
        self._state_diff_hash: Dict[str, str] = {}
    
    @property
    def template_diff_sent(self) -> bool:
        """Check if template diff has been sent."""
        return self._template_diff_sent
    
    def mark_template_diff_sent(self):
        """Mark template diff as sent."""
        self._template_diff_sent = True
    
    def is_diff_changed(self, diff: str) -> bool:
        """Check if diff has changed from previous."""
        current_hash = hash_diff(diff)
        return current_hash != self._prev_diff_hash
    
    def update_diff_hash(self, diff: str):
        """Update the previous diff hash."""
        self._prev_diff_hash = hash_diff(diff)
    
    def should_skip_state_diff(self, state: str, diff: str) -> bool:
        """Check if diff for a given state should be skipped."""
        diff_hash = hash_diff(diff)
        
        if self._state_diff_hash.get(state) == diff_hash:
            logger.info(
                "Diff for state %s unchanged (hash=%s), skipping duplicate",
                state,
                diff_hash,
            )
            return True
        
        # Cache hash for this state
        self._state_diff_hash[state] = diff_hash
        return False 