"""Orchestration: resolve (config+preset+platform) then lazily ensure downloads."""
from pathlib import Path

from .platform import current_platform
from .registry import CAPABILITIES, PRESETS, MODELS, by_id, for_capability_tier
from .config import load_config, save_config
from .download import ensure as _ensure, is_present, DownloadDeclined

USER_TIERED = ("asr", "embedding", "vlm")   # capabilities with a user preset axis


class ModelManager:
    def __init__(self, state_dir, platform: str | None = None):
        self.state_dir = Path(state_dir)
        self.models_root = self.state_dir / "models"
        self.platform = platform or current_platform()

    # --- resolution ---
    def resolve(self, capability: str):
        cfg = load_config(self.state_dir)
        if capability == "ocr":
            return self._resolve_ocr()
        override = cfg.overrides.get(capability)
        if override == "off":
            return None
        if override:
            spec = by_id(override)
            if spec and spec.capability == capability:
                return spec
        # fall back to preset tier
        tier = cfg.preset
        if capability == "vlm" and tier == "light":
            return None                      # vlm light == off
        return for_capability_tier(capability, tier)

    def _resolve_ocr(self):
        for m in _ocr_models():
            if m.artifact_for(self.platform):
                return m
        return None

    # --- choices ---
    def set_preset(self, preset: str) -> None:
        if preset not in PRESETS:
            raise ValueError("unknown preset %r" % preset)
        cfg = load_config(self.state_dir)
        cfg.preset = preset
        save_config(self.state_dir, cfg)

    def set_choice(self, capability: str, tier_or_model_id: str) -> None:
        if capability not in USER_TIERED:
            raise ValueError("capability %r is not user-selectable" % capability)
        cfg = load_config(self.state_dir)
        val = tier_or_model_id
        if val == "off":
            if capability != "vlm":
                raise ValueError("only vlm may be turned off")
            cfg.overrides[capability] = "off"
        elif capability == "vlm" and val == "light":
            cfg.overrides[capability] = "off"
        elif val in PRESETS:
            spec = for_capability_tier(capability, val)
            if spec is None:
                raise ValueError("no %s model for tier %r" % (capability, val))
            cfg.overrides[capability] = spec.id
        else:
            spec = by_id(val)
            if spec is None or spec.capability != capability:
                raise ValueError("%r is not a %s model" % (val, capability))
            cfg.overrides[capability] = spec.id
        save_config(self.state_dir, cfg)

    # --- download ---
    def ensure(self, capability, fetcher=None, confirm=None):
        spec = self.resolve(capability)
        if spec is None:
            return None
        return _ensure(self.models_root, spec, self.platform, fetcher=fetcher, confirm=confirm)

    def prefetch(self, fetcher=None, confirm=None) -> dict:
        out = {}
        for cap in CAPABILITIES:
            spec = self.resolve(cap)
            if spec is None:
                out[cap] = "off"
                continue
            try:
                self.ensure(cap, fetcher=fetcher, confirm=confirm)
                out[cap] = "ok"
            except DownloadDeclined:
                out[cap] = "declined"
            except Exception as e:
                out[cap] = "error:%s" % e
        return out

    # --- status ---
    def status(self) -> dict:
        cfg = load_config(self.state_dir)
        caps = {}
        for cap in CAPABILITIES:
            spec = self.resolve(cap)
            if spec is None:
                caps[cap] = {"selected_id": None, "tier": None, "present": False, "size_mb": 0}
                continue
            art = spec.artifact_for(self.platform)
            caps[cap] = {
                "selected_id": spec.id,
                "tier": spec.tier,
                "present": is_present(self.models_root, spec),
                "size_mb": art.size_mb if art else 0,
            }
        return {"preset": cfg.preset, "platform": self.platform, "capabilities": caps}


def _ocr_models():
    return [m for m in MODELS if m.capability == "ocr"]
