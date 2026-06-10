from __future__ import annotations

import importlib


MODULES = (
    "cogs.settings",
    "cogs.game_control",
    "cogs.status_stats",
    "cogs.info",
)


def load_all() -> None:
    for module_name in MODULES:
        importlib.import_module(module_name)
