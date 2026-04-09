import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Type

from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.config import StrategyConfig


class StrategyInfo:
    def __init__(
        self,
        name: str,
        module: ModuleType,
        strategy_cls: Type[Strategy],
        cfg_cls: Type[StrategyConfig],
    ):
        self.name = name
        self.module = module
        self.strategy_cls = strategy_cls
        self.cfg_cls = cfg_cls
        # Store the class docstring or an empty string, trimmed
        self.doc = (strategy_cls.__doc__ or "").strip()


def _import(py: Path) -> ModuleType:
    """
    Dynamically import a Python module from a file path.
    """
    spec = importlib.util.spec_from_file_location(py.stem, py)
    mod = importlib.util.module_from_spec(spec)
    # Register module under its file stem name
    sys.modules[py.stem] = mod
    # Execute the module code in its own namespace
    spec.loader.exec_module(mod)         # type: ignore[attr-defined]
    return mod


def discover_strategies(root: str = "strategies") -> Dict[str, StrategyInfo]:
    """
    Discover and load trading strategy classes and their configurations.

    Steps:
    1) If '<root>/admin.py' exists and defines a _REGISTRY, use it directly.
    2) Otherwise, recursively scan all .py files under root for pairs of
       (Strategy subclass, StrategyConfig subclass).

    Behavior notes:

    - The scan is **recursive** (``rglob``) so projects can organize strategies
      by market type, e.g. ``strategies/forex/ema_cross.py``,
      ``strategies/crypto/grid_bot.py``. This matches the layout documented
      in the nautilus-trading project CLAUDE.md.
    - ``__pycache__``, ``__init__.py`` and dunder files are skipped.
    - If the specified ``root`` directory does not exist, fall back to the
      current directory. This prevents the dashboard from failing on a bare
      repository without a strategies subpackage.
    - Modules whose stem collides with a previously loaded strategy are
      registered under the fully qualified file stem so both can coexist.
    """
    root_path = Path(root)
    if not root_path.exists():
        # Fall back to current directory if the strategies folder is missing
        root_path = Path(".")

    admin = root_path / "admin.py"
    if admin.is_file():
        mod = _import(admin)
        if hasattr(mod, "_REGISTRY"):
            # Build StrategyInfo from the registry mapping
            return {
                name: StrategyInfo(name, mod, strat_cls, cfg_cls)  # type: ignore
                for name, (strat_cls, cfg_cls) in mod._REGISTRY.items()
            }

    infos: Dict[str, StrategyInfo] = {}
    # Recursively scan all .py files under the root path
    for py in sorted(root_path.rglob("*.py")):
        # Skip dunder files, cached compiled files and admin.py
        if py.name.startswith("_") or py.name == "admin.py":
            continue
        if "__pycache__" in py.parts:
            continue
        try:
            mod = _import(py)
        except Exception as exc:
            rel = py.relative_to(root_path) if py.is_relative_to(root_path) else py
            print(f"[loader] skipping {rel}: {exc}")
            continue

        strat_cls = None
        cfg_cls = None
        # Inspect module members for Strategy and StrategyConfig subclasses
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, Strategy) and cls is not Strategy:
                strat_cls = cls
            if issubclass(cls, StrategyConfig) and cls is not StrategyConfig:
                cfg_cls = cls
        # If both a strategy and its config are found, record them
        if strat_cls and cfg_cls:
            key = strat_cls.__name__
            if key in infos:
                # Disambiguate with relative path stem to avoid clobbering
                rel_parts = py.relative_to(root_path).with_suffix("").parts
                key = f"{strat_cls.__name__} ({'/'.join(rel_parts)})"
            infos[key] = StrategyInfo(key, mod, strat_cls, cfg_cls)
    return infos
