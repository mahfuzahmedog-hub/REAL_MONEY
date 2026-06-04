"""Instagram posting client (instagrapi-based).

Scaffolded in Step 1. Full implementation in Step 6.

Uses instagrapi 2.1.0 (unofficial Instagram private API).
Risk: Meta may flag logins. Sessions are cached to .ig_session.json.
"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("instagram")

SESSION_PATH = Path(__file__).resolve().parent / ".ig_session.json"


class InstagramClient:
    def __init__(self):
        self.client = None
        self.username: Optional[str] = None
        self._last_post_at: Optional[float] = None

    def is_logged_in(self) -> bool:
        return self.client is not None

    def get_status(self) -> dict:
        return {
            "logged_in": self.is_logged_in(),
            "username": self.username,
            "last_post_at": self._last_post_at,
        }

    def login(self, username: str, password: str, verification_code: Optional[str] = None) -> dict:
        raise NotImplementedError("Step 6 will implement instagrapi login")

    def logout(self) -> None:
        self.client = None
        self.username = None
        if SESSION_PATH.exists():
            SESSION_PATH.unlink(missing_ok=True)

    def post_reel(self, video_path: Path, caption: str) -> dict:
        raise NotImplementedError("Step 6 will implement instagrapi post_reel")


_singleton: Optional[InstagramClient] = None


def get_client() -> InstagramClient:
    global _singleton
    if _singleton is None:
        _singleton = InstagramClient()
    return _singleton
