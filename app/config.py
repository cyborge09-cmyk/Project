"""Environment-driven settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    session_secret: str
    cookie_secure: bool
    session_max_age: int

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def rest_url(self) -> str:
        return f"{self.supabase_url}/rest/v1"

    @property
    def auth_url(self) -> str:
        return f"{self.supabase_url}/auth/v1"


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        supabase_url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        # Only used to sign the session cookie; a random value logs everyone out on restart.
        session_secret=os.environ.get("SESSION_SECRET", os.urandom(32).hex()),
        cookie_secure=_bool("COOKIE_SECURE", os.environ.get("VERCEL_ENV") is not None),
        session_max_age=int(os.environ.get("SESSION_MAX_AGE", 60 * 60 * 24 * 7)),
    )
