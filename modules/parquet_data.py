# parquet_data.py
# -*- coding: utf-8 -*-
"""
parquet_data — load OHLCV bars from a NautilusTrader ParquetDataCatalog
directory into a pandas.DataFrame matching the schema produced by
``csv_data.load_ohlcv_csv`` (DatetimeIndex UTC + open/high/low/close/volume).

Uses ``pyarrow`` directly to avoid importing the full
``nautilus_trader.persistence.catalog`` machinery. NautilusTrader writes
OHLCV columns as ``fixed_size_binary[16]`` — a little-endian 128-bit signed
integer scaled by ``FIXED_SCALAR`` (``10 ** FIXED_PRECISION``, which is
``10 ** 16`` in the high-precision build shipped with v1.224.0).

Catalog layout expected::

    <data_dir>/
    └── data/
        └── bar/
            └── <bar_type>/
                └── <start>_<end>.parquet

or, if ``data_dir`` already points at a venue subdirectory (e.g. ``.../binance``),
the ``data/bar/`` subtree beneath it is used.

Missing directories return an empty DataFrame with the expected columns
rather than raising — callers should treat empty as "no data yet".
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

import pandas as pd

__all__ = [
    "load_ohlcv_parquet",
    "list_bar_types",
    "BAR_TYPE_RE",
    "FIXED_SCALAR",
]

_logger = logging.getLogger(__name__)

# Matches a full Nautilus bar type directory name, e.g.
# ``BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL``. Declared here (rather than
# imported from ``data_connector``) to keep this module importable without
# a circular dependency — ``data_connector`` already imports from here.
BAR_TYPE_RE = re.compile(
    r"^[A-Z0-9]+\.[A-Z]+-\d+-[A-Z]+-[A-Z]+-[A-Z]+$"
)

# NautilusTrader v1.224.0 high-precision build uses int128 raw values scaled
# by 10**16. Hard-coded to avoid importing ``nautilus_trader.core.nautilus_pyo3``
# (which is a heavy Rust extension) just for a constant.
FIXED_PRECISION: int = 16
FIXED_SCALAR: float = 10.0 ** FIXED_PRECISION

_EXPECTED_COLUMNS: List[str] = ["open", "high", "low", "close", "volume"]


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame shaped like a successful load."""
    idx = pd.DatetimeIndex([], tz="UTC", name="timestamp")
    return pd.DataFrame({c: pd.Series(dtype="float64") for c in _EXPECTED_COLUMNS}, index=idx)


def _decode_int128_column(arr) -> "pd.Series":
    """
    Decode a pyarrow ``fixed_size_binary[16]`` column into a float64 Series
    using little-endian signed int128 interpretation scaled by FIXED_SCALAR.
    """
    # ``arr.to_pylist()`` yields ``bytes`` objects of length 16.
    raw_bytes = arr.to_pylist()
    values = [
        (int.from_bytes(b, "little", signed=True) / FIXED_SCALAR) if b is not None else float("nan")
        for b in raw_bytes
    ]
    return pd.Series(values, dtype="float64")


def _find_bar_dir(root: Path) -> Optional[Path]:
    """
    Resolve the ``data/bar`` directory for a catalog root.

    Accepts either the catalog root (containing ``data/bar/``) or a subpath
    one level up (containing a venue dir whose subtree holds ``data/bar/``).
    Returns ``None`` if no bar directory exists.
    """
    if not root.exists() or not root.is_dir():
        return None

    # Direct layout: <root>/data/bar/
    direct = root / "data" / "bar"
    if direct.is_dir():
        return direct

    # Nested venue layout: <root>/<venue>/data/bar/ — take first match.
    for child in sorted(root.iterdir()):
        if child.is_dir():
            nested = child / "data" / "bar"
            if nested.is_dir():
                return nested

    return None


def list_bar_types(data_dir: str | Path) -> List[str]:
    """
    Return the list of bar_type names available under a catalog root.

    Parameters
    ----------
    data_dir : str | Path
        Path to a NautilusTrader ParquetDataCatalog root.

    Returns
    -------
    list[str]
        Bar type identifiers (directory names under ``data/bar/``).
        Empty list if the path is missing or contains no bar data.
    """
    root = Path(data_dir)
    bar_dir = _find_bar_dir(root)
    if bar_dir is None:
        return []
    return sorted(p.name for p in bar_dir.iterdir() if p.is_dir())


def load_ohlcv_parquet(
    data_dir: str | Path,
    bar_type: str,
) -> pd.DataFrame:
    """
    Read all ``*.parquet`` files for a given bar_type from a Nautilus
    ParquetDataCatalog and return a DataFrame matching ``load_ohlcv_csv``.

    Parameters
    ----------
    data_dir : str | Path
        Path to a NautilusTrader ParquetDataCatalog root.
    bar_type : str
        Bar type identifier (e.g. ``"BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"``).

    Returns
    -------
    pandas.DataFrame
        Columns: ``open``, ``high``, ``low``, ``close``, ``volume`` (float64).
        Index: ``DatetimeIndex`` (UTC, sorted, named ``timestamp``).
        Empty DataFrame with the expected schema if the bar_type directory
        does not exist or contains no rows.
    """
    if not isinstance(bar_type, str) or not BAR_TYPE_RE.match(bar_type):
        raise ValueError(
            f"bar_type {bar_type!r} is not a valid Nautilus bar type string "
            "(expected e.g. 'BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL'); "
            "use DataConnector.get_parquet_bar_type(exchange, symbol, timeframe) "
            "to compose one."
        )

    try:
        import pyarrow.parquet as pq  # Local import: heavy dep, defer.
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "pyarrow is required for parquet data loading. "
            "Install it via `uv pip install pyarrow>=16.0.0`."
        ) from exc

    root = Path(data_dir)
    bar_dir = _find_bar_dir(root)
    if bar_dir is None:
        _logger.debug("No data/bar directory found under %s", root)
        return _empty_frame()

    target_dir = bar_dir / bar_type
    if not target_dir.is_dir():
        _logger.debug("Bar type %s not found under %s", bar_type, bar_dir)
        return _empty_frame()

    parquet_files = sorted(target_dir.glob("*.parquet"))
    if not parquet_files:
        return _empty_frame()

    frames: List[pd.DataFrame] = []
    for pf in parquet_files:
        table = pq.read_table(pf)
        # Required columns — if any are missing we treat the file as unreadable.
        missing = [c for c in (*_EXPECTED_COLUMNS, "ts_event") if c not in table.column_names]
        if missing:
            _logger.warning("Parquet file %s missing columns %s — skipping", pf, missing)
            continue

        price_cols = {c: _decode_int128_column(table.column(c)) for c in _EXPECTED_COLUMNS}
        ts_event = pd.to_datetime(
            table.column("ts_event").to_pandas(),
            unit="ns",
            utc=True,
        )
        df_part = pd.DataFrame(price_cols)
        df_part.index = pd.DatetimeIndex(ts_event, name="timestamp")
        frames.append(df_part)

    if not frames:
        return _empty_frame()

    df = pd.concat(frames)
    df.sort_index(inplace=True)
    # Drop exact duplicates on (timestamp, close) — catalogs can have overlaps
    # at chunk boundaries. Keeping the first preserves the earliest write.
    df = df[~df.index.duplicated(keep="first")]
    _logger.debug("Loaded %d rows for %s from %s", len(df), bar_type, target_dir)
    return df
