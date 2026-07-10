"""User model choices persisted under the plugin state dir."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .registry import PRESETS


@dataclass
class Config:
    preset: str = "light"
    overrides: dict = field(default_factory=dict)   # capability -> model_id


def config_path(state_dir) -> Path:
    return Path(state_dir) / "models" / "config.json"


def load_config(state_dir) -> Config:
    p = config_path(state_dir)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    preset = data.get("preset", "light")
    if preset not in PRESETS:
        preset = "light"
    overrides = data.get("overrides") or {}
    if not isinstance(overrides, dict):
        overrides = {}
    return Config(preset=preset, overrides={str(k): str(v) for k, v in overrides.items()})


def save_config(state_dir, config: Config) -> None:
    p = config_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(
        {"preset": config.preset, "overrides": config.overrides},
        ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
