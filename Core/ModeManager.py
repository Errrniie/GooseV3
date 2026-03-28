"""
Registers modes from `Modes/` and connects API-driven selection to the orchestrator.

The control API calls `select_mode()`; `wait_for_pipeline()` blocks until then.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Dict

from Modes import Normal_Mode
from Modes import Test_Mode

Pipeline = Callable[[], None]

_REGISTRY: Dict[str, Pipeline] = {
    "normal": Normal_Mode.run,
    "test": Test_Mode.run,
}

_lock = threading.Lock()
_selected: Pipeline | None = None
_mode_ready = threading.Event()


def list_registered_modes() -> list[str]:
    return sorted(_REGISTRY.keys())


def select_mode(mode_id: str) -> bool:
    """Called from the control API when a client selects a mode."""
    key = mode_id.strip().lower()
    pipeline = _REGISTRY.get(key)
    if pipeline is None:
        return False
    global _selected
    with _lock:
        _selected = pipeline
    _mode_ready.set()
    return True


def wait_for_pipeline() -> Pipeline:
    """Block until `select_mode()` succeeds (e.g. via HTTP). Returns the pipeline to run."""
    _mode_ready.wait()
    with _lock:
        if _selected is None:
            raise RuntimeError("Mode ready event set but no pipeline is selected")
        return _selected
