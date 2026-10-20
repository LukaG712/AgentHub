"""Auto Review: pattern-based action detection for sensitive operations.

Checks agent output against configurable patterns (git push, rm -rf, etc.)
and returns the first matching pattern, or None if no match.
"""

import re
from typing import List, Optional, Tuple

from hub.config import load_config


def get_patterns() -> List[str]:
    """Get the configured auto-review patterns from hub.yaml."""
    config = load_config()
    auto_review = config.get("auto_review", {})
    patterns = auto_review.get("patterns", [])
    if not patterns:
        # Default sensitive patterns
        patterns = [
            r"git\s+push\b",
            r"rm\s+-rf\b",
            r"curl\s+https?://",
            r"wget\s+https?://",
            r"pip\s+install\b",
            r"apt\s+install\b",
            r"chmod\s+[0-7]*777\b",
        ]
    return patterns


def check_action(text: str) -> Optional[Tuple[str, str]]:
    """Check if text matches any sensitive action pattern.

    Returns (pattern, matched_text) if a match is found, None otherwise.
    """
    patterns = get_patterns()
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return (pattern, match.group(0))
    return None


def is_enabled() -> bool:
    """Check if auto-review is enabled in config."""
    config = load_config()
    auto_review = config.get("auto_review", {})
    return auto_review.get("enabled", False)
