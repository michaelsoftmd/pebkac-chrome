"""
API route modules
"""

from app.api.routes import (
    health,
    browser,
    interaction,
    extraction,
    network,
    capture,
    agent
)

__all__ = [
    "health",
    "browser",
    "interaction",
    "extraction",
    "network",
    "capture",
    "agent"
]
