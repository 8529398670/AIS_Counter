"""Config for tests, the way the server holds it now: through a
config_live.Holder, which hands out the running Config per request
(app/core/config_live.py)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.core import config, config_live, config_secret


def fake_holder(cfg: Any) -> SimpleNamespace:
    """A stand-in Holder over any object, for code that only reads settings."""
    return SimpleNamespace(get=lambda: cfg, boot=lambda: cfg, on_change=lambda listener: None)


def real_holder(tmp_path: Path, **changes: Any) -> config_live.Holder:
    """A Holder over a real config.yaml (the defaults) and secret.key under
    tmp_path, with its data in tmp_path/data, then changes on top."""
    folder = tmp_path / "config"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.yaml"
    config.write_new(path)
    raw = path.read_text(encoding="utf-8").replace('app_dir: ""', f'app_dir: "{tmp_path / "data"}"', 1)
    path.write_text(raw, encoding="utf-8")
    file = config.read_file(path)
    cfg = config.build_config(file, path, config.resolve_paths(file, path), config_secret.read_secret(config_secret.secret_path_for(path)))
    cfg = replace(cfg, raw=config_live.read_raw(path), logs=replace(cfg.logs, enabled=False), **changes)
    cfg.app_dir.mkdir(parents=True, exist_ok=True)
    holder = config_live.Holder(cfg)
    holder._current = cfg
    return holder
