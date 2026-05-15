from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _exe_dir() -> Path:
    """Return the directory containing the executable, or cwd if not frozen."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path.cwd()


def _resource_path(relative: str) -> str:
    """Return absolute path to a bundled resource, handling frozen environments."""
    if getattr(sys, 'frozen', False):
        return os.path.join(getattr(sys, '_MEIPASS'), relative)
    return os.path.abspath(relative)


def _find_config_path() -> Path:
    """Find config.yaml: use exe directory. Auto-copy built-in if not present."""
    exe_config = _exe_dir() / "config.yaml"
    if exe_config.exists():
        return exe_config
    # Copy bundled config to exe directory on first run
    bundled = Path(_resource_path("config.yaml"))
    if bundled.exists():
        shutil.copy2(str(bundled), str(exe_config))
    return exe_config


def _resolve_db_path(relative_path: str) -> str:
    """Make relative sqlite paths resolve to exe directory, not cwd."""
    if relative_path.startswith(("./", "data/")) and getattr(sys, 'frozen', False):
        return str(_exe_dir() / relative_path)
    return relative_path


CONFIG_PATH = _find_config_path()


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1


class ProviderConfig(BaseModel):
    name: str = "default"
    provider: Literal["openai", "anthropic"] = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com"
    timeout: int = 120
    models: list[str] = []
    default: bool = False


class UpstreamConfig(BaseModel):
    provider: Literal["openai", "anthropic"] = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com"
    timeout: int = 120
    providers: list[ProviderConfig] = []

    def get_provider_for_model(self, model: str) -> ProviderConfig:
        """Select provider: exact match → prefix match → default → first."""
        if not self.providers:
            return ProviderConfig(
                name="legacy", provider=self.provider,
                api_key=self.api_key, base_url=self.base_url,
                timeout=self.timeout, default=True,
            )
        for p in self.providers:
            if model in p.models:
                return p
        for p in self.providers:
            for prefix in p.models:
                if model.startswith(prefix):
                    return p
        for p in self.providers:
            if p.default:
                return p
        return self.providers[0]


class SqliteDBConfig(BaseModel):
    path: str = "./data/proxy.db"


class PostgresDBConfig(BaseModel):
    url: str = ""


class MySQLDBConfig(BaseModel):
    url: str = ""


class DatabaseConfig(BaseModel):
    driver: Literal["sqlite", "postgresql", "mysql"] = "sqlite"
    sqlite: SqliteDBConfig = Field(default_factory=SqliteDBConfig)
    postgresql: PostgresDBConfig = Field(default_factory=PostgresDBConfig)
    mysql: MySQLDBConfig = Field(default_factory=MySQLDBConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = {"extra": "allow"}


def _load_yaml_config(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _apply_env_overrides(config: dict) -> dict:
    env_map = {
        "PROXY_HOST": ("server", "host"),
        "PROXY_PORT": ("server", "port"),
        "UPSTREAM_PROVIDER": ("upstream", "provider"),
        "UPSTREAM_API_KEY": ("upstream", "api_key"),
        "UPSTREAM_BASE_URL": ("upstream", "base_url"),
        "UPSTREAM_TIMEOUT": ("upstream", "timeout"),
        "DATABASE_DRIVER": ("database", "driver"),
        "DATABASE_SQLITE_PATH": ("database", "sqlite", "path"),
        "DATABASE_POSTGRESQL_URL": ("database", "postgresql", "url"),
        "DATABASE_MYSQL_URL": ("database", "mysql", "url"),
        "LOGGING_LEVEL": ("logging", "level"),
    }
    for env_var, keys in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            target = config
            for k in keys[:-1]:
                target = target.setdefault(k, {})
            if keys[-1] in ("port", "timeout"):
                target[keys[-1]] = int(value)
            else:
                target[keys[-1]] = value
    return config


def load_config() -> AppConfig:
    raw = _load_yaml_config(CONFIG_PATH)
    raw = _apply_env_overrides(raw)
    # Resolve relative sqlite paths to exe directory
    if raw.get("database", {}).get("sqlite", {}).get("path", "").startswith(("./", "data/")):
        raw["database"]["sqlite"]["path"] = _resolve_db_path(raw["database"]["sqlite"]["path"])
    return AppConfig(**raw)


settings = load_config()


def reload_settings() -> AppConfig:
    """Reload settings from config file and return new settings."""
    global settings
    settings = load_config()
    return settings
