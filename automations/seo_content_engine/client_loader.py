"""Loads + validates per-client config for the SEO content engine.

Layout expected:
    business-os/clients/{name}/seo-engine/
        client.yaml
        brand-voice.md
        content-plan.yaml
        audit.yaml
        publish_log.yaml
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parent
BUSINESS_OS = ENGINE_DIR.parent.parent  # business-os/
CLIENTS_DIR = BUSINESS_OS / "clients"

REQUIRED_TOP_KEYS = {"name", "active", "site", "language", "cadence",
                     "publish_day", "publish_time", "timezone",
                     "min_quality_score", "voice_file", "telegram_chat_id",
                     "audit_file", "content_plan_file"}
REQUIRED_SITE_KEYS = {"url", "cms", "api_user_env", "api_password_env"}


@dataclass
class ClientConfig:
    name: str
    active: bool
    site_url: str
    cms: str
    api: str                   # "rest" | "xmlrpc"
    api_user: str
    api_password: str
    language: str
    cadence: str               # weekly | biweekly | monthly
    publish_day: str           # mon..sun
    publish_time: str          # HH:MM (local TZ)
    timezone: str
    min_quality_score: int
    telegram_chat_id: int
    seo_dir: Path
    voice_file: Path
    audit_file: Path
    content_plan_file: Path
    publish_log_file: Path

    @property
    def voice(self) -> str:
        if self.voice_file.exists():
            return self.voice_file.read_text(encoding="utf-8")
        return ""


def _load_dotenv() -> None:
    """Load business-os/.env into os.environ if present (idempotent)."""
    env_path = BUSINESS_OS / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def load_registry() -> list[dict]:
    """Read clients.yaml registry."""
    registry = ENGINE_DIR / "clients.yaml"
    data = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    return data.get("clients", [])


def list_active_clients() -> list[str]:
    return [c["name"] for c in load_registry() if c.get("active")]


def load_client(name: str) -> ClientConfig:
    """Load + validate a client's config. Raises on missing files / keys / env."""
    _load_dotenv()

    seo_dir = CLIENTS_DIR / name / "seo-engine"
    cfg_path = seo_dir / "client.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Missing client config: {cfg_path}")

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    missing = REQUIRED_TOP_KEYS - cfg.keys()
    if missing:
        raise ValueError(f"{name}: client.yaml missing keys: {sorted(missing)}")

    site = cfg.get("site") or {}
    site_missing = REQUIRED_SITE_KEYS - site.keys()
    if site_missing:
        raise ValueError(f"{name}: client.yaml site missing keys: {sorted(site_missing)}")

    api_user = os.environ.get(site["api_user_env"], "").strip()
    api_password = os.environ.get(site["api_password_env"], "").strip()
    if not api_user or not api_password:
        raise EnvironmentError(
            f"{name}: env vars {site['api_user_env']} / {site['api_password_env']} "
            "not set in business-os/.env"
        )

    return ClientConfig(
        name=cfg["name"],
        active=bool(cfg["active"]),
        site_url=site["url"].rstrip("/"),
        cms=site["cms"],
        api=str(site.get("api", "rest")).lower(),
        api_user=api_user,
        api_password=api_password,
        language=cfg["language"],
        cadence=cfg["cadence"],
        publish_day=cfg["publish_day"].lower(),
        publish_time=cfg["publish_time"],
        timezone=cfg["timezone"],
        min_quality_score=int(cfg["min_quality_score"]),
        telegram_chat_id=int(cfg["telegram_chat_id"]),
        seo_dir=seo_dir,
        voice_file=seo_dir / cfg["voice_file"],
        audit_file=seo_dir / cfg["audit_file"],
        content_plan_file=seo_dir / cfg["content_plan_file"],
        publish_log_file=seo_dir / "publish_log.yaml",
    )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        c = load_client(target)
        print(f"OK: {c.name} ({c.site_url}, {c.language}, {c.cadence})")
    else:
        for n in list_active_clients():
            print(n)
