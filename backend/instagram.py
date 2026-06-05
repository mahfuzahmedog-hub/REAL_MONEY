"""Instagram posting client (instagrapi-based).

Uses instagrapi 2.0.3 (unofficial Instagram private API).
Risk: Meta may flag logins. Sessions are cached to .ig_session.json.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("instagram")

SESSION_PATH = Path(__file__).resolve().parent / ".ig_session.json"


class InstagramClient:
    def __init__(self):
        self.client = None
        self.username: Optional[str] = None
        self._last_post_at: Optional[float] = None
        self._load_session()

    def is_logged_in(self) -> bool:
        return self.client is not None

    def get_status(self) -> dict:
        return {
            "logged_in": self.is_logged_in(),
            "username": self.username,
            "last_post_at": self._last_post_at,
        }

    def _load_session(self) -> None:
        if not SESSION_PATH.exists():
            return
        try:
            data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            if not data.get("username"):
                return
            from instagrapi import Client
            self.client = Client()
            self.client.load_settings(SESSION_PATH)
            self.username = data["username"]
            try:
                self.client.get_timeline_feed()
                logger.info(f"[instagram] session restored for @{self.username}")
            except Exception as e:
                logger.warning(f"[instagram] session expired or invalid: {e}")
                self.client = None
                self.username = None
                SESSION_PATH.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"[instagram] failed to load session: {e}")
            self.client = None
            self.username = None

    def _save_session(self) -> None:
        if self.client is None:
            return
        try:
            self.client.dump_settings(SESSION_PATH)
            data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            data["username"] = self.username
            data["saved_at"] = time.time()
            SESSION_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[instagram] failed to save session: {e}")

    def login(self, username: str, password: str, verification_code: Optional[str] = None) -> dict:
        try:
            from instagrapi import Client
            from instagrapi.exceptions import (
                TwoFactorRequired,
                ChallengeRequired,
                BadPassword,
                UnknownError,
            )
        except ImportError:
            return {"ok": False, "error": "instagrapi not installed. Run: pip install instagrapi==2.0.3"}

        try:
            self.client = Client()
            self.client.login(username, password, verification_code=verification_code or "")
            self.username = username
            self._save_session()
            logger.info(f"[instagram] logged in as @{username}")
            return {"ok": True, "username": username}
        except TwoFactorRequired:
            return {"ok": False, "requires_2fa": True, "error": "2FA code required"}
        except BadPassword:
            return {"ok": False, "error": "Wrong password"}
        except ChallengeRequired:
            return {
                "ok": False,
                "error": "Instagram challenge required. Open the Instagram app, verify the login, then try again.",
            }
        except Exception as e:
            logger.error(f"[instagram] login failed: {e}")
            return {"ok": False, "error": str(e)}

    def logout(self) -> None:
        self.client = None
        self.username = None
        if SESSION_PATH.exists():
            SESSION_PATH.unlink(missing_ok=True)
        logger.info("[instagram] logged out")

    def post_reel(self, video_path: Path, caption: str) -> dict:
        if not self.is_logged_in():
            return {"ok": False, "error": "Not logged in. Go to Settings to log in."}
        if not video_path.exists():
            return {"ok": False, "error": f"Video not found: {video_path}"}

        try:
            from instagrapi.exceptions import (
                TwoFactorRequired,
                ChallengeRequired,
                MediaError,
                ClientError,
            )
        except ImportError:
            return {"ok": False, "error": "instagrapi not installed"}

        try:
            logger.info(f"[instagram] posting reel {video_path.name} ({video_path.stat().st_size/1e6:.1f} MB)")
            media = self.client.clip_upload(
                path=str(video_path),
                caption=caption,
            )
            self._last_post_at = time.time()
            self._save_session()
            permalink = f"https://www.instagram.com/reel/{media.code}/" if hasattr(media, "code") and media.code else None
            logger.info(f"[instagram] posted! media_id={media.id} code={getattr(media, 'code', None)}")
            return {
                "ok": True,
                "media_id": str(media.id),
                "permalink": permalink,
            }
        except (TwoFactorRequired, ChallengeRequired):
            return {"ok": False, "error": "Re-authentication required. Log in again from Settings."}
        except Exception as e:
            logger.error(f"[instagram] post failed: {e}")
            return {"ok": False, "error": str(e)}


_singleton: Optional[InstagramClient] = None


def get_client() -> InstagramClient:
    global _singleton
    if _singleton is None:
        _singleton = InstagramClient()
    return _singleton
