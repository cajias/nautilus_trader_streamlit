# data_connector.py
# -*- coding: utf-8 -*-
"""Unified interface for loading OHLCV data from CSV, Parquet catalog, or ClickHouse."""

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import re

import pandas as pd

from .csv_data import load_ohlcv_csv
from .parquet_data import list_bar_types, load_ohlcv_parquet
from .clickhouse import ClickHouseConnector

__all__ = ["DataConnector"]


CSV_NAME_RE = re.compile(r"(?P<ex>[A-Z]+)_(?P<sym>[A-Z]+),\s*(?P<tf>\d+)\.csv")

# Parse bar_type directory names like "BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"
# into (symbol, venue, interval, unit).
BAR_TYPE_RE = re.compile(
    r"(?P<sym>[A-Z0-9]+)\.(?P<ex>[A-Z]+)-(?P<n>\d+)-(?P<unit>[A-Z]+)-[A-Z]+-[A-Z]+"
)


class DataConnector:
    """Load OHLCV data and expose available sources.

    Parameters
    ----------
    data_dir : str | Path, optional
        Root directory for CSV files or a NautilusTrader ParquetDataCatalog.
        Defaults to the current working directory (``"."``).
    clickhouse_params : dict, optional
        Kwargs forwarded to :class:`ClickHouseConnector`.
    source : str, optional
        Default source (``"CSV"``, ``"PARQUET"``, or ``"CLICKHOUSE"``). Only
        used by :meth:`default_source`; individual methods still accept an
        explicit ``source`` argument.
    csv_dir : str | Path, optional
        Deprecated alias for ``data_dir``. Kept for backward compatibility
        with the upstream API. If both are supplied, ``data_dir`` wins and
        a ``DeprecationWarning`` is emitted.
    """

    def __init__(
        self,
        data_dir: str | Path | None = None,
        clickhouse_params: Optional[Dict[str, Any]] = None,
        *,
        source: str = "CSV",
        csv_dir: str | Path | None = None,
    ) -> None:
        if csv_dir is not None:
            warnings.warn(
                "DataConnector(csv_dir=...) is deprecated; use data_dir instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            if data_dir is None:
                data_dir = csv_dir
        if data_dir is None:
            data_dir = "."

        self._data_dir = Path(data_dir)
        self._default_source = source.upper()
        self._csv_info: Optional[List[Dict[str, str]]] = None
        self._parquet_info: Optional[List[Dict[str, str]]] = None
        self._ch_params = clickhouse_params or {}
        self._ch: Optional[ClickHouseConnector] = None

    # ------------------------------------------------------------------
    # Compatibility shims
    # ------------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def csv_dir(self) -> Path:
        """Deprecated alias for :attr:`data_dir`."""
        return self._data_dir

    @property
    def default_source(self) -> str:
        return self._default_source

    # ------------------------------------------------------------------
    # Source scanners
    # ------------------------------------------------------------------
    def _scan_csv(self) -> List[Dict[str, str]]:
        """Return cached info about CSV files."""
        if self._csv_info is None:
            info: List[Dict[str, str]] = []
            if self._data_dir.is_dir():
                for p in self._data_dir.glob("*.csv"):
                    m = CSV_NAME_RE.match(p.name)
                    if m:
                        tf = f"{m.group('tf')}min"
                        info.append(
                            {
                                "path": str(p),
                                "exchange": m.group("ex"),
                                "symbol": m.group("sym"),
                                "timeframe": tf,
                            }
                        )
            self._csv_info = info
        return self._csv_info

    def _scan_parquet(self) -> List[Dict[str, str]]:
        """Return cached info about parquet bar_types in the catalog."""
        if self._parquet_info is None:
            info: List[Dict[str, str]] = []
            for bar_type in list_bar_types(self._data_dir):
                m = BAR_TYPE_RE.match(bar_type)
                if not m:
                    continue
                unit = m.group("unit")
                n = int(m.group("n"))
                if unit == "MINUTE":
                    tf = f"{n}min"
                elif unit == "HOUR":
                    tf = f"{n * 60}min"
                elif unit == "DAY":
                    tf = f"{n * 1440}min"
                else:
                    tf = f"{n}{unit.lower()}"
                info.append(
                    {
                        "bar_type": bar_type,
                        "exchange": m.group("ex"),
                        "symbol": m.group("sym"),
                        "timeframe": tf,
                    }
                )
            self._parquet_info = info
        return self._parquet_info

    def _get_ch(self) -> ClickHouseConnector:
        if self._ch is None:
            self._ch = ClickHouseConnector(**self._ch_params)
        return self._ch

    # ------------------------------------------------------------------
    # Public enumeration API
    # ------------------------------------------------------------------
    def get_exchanges(self, source: str) -> List[str]:
        source_u = source.upper()
        if source_u == "CSV":
            return sorted({i["exchange"] for i in self._scan_csv()})
        if source_u == "PARQUET":
            return sorted({i["exchange"] for i in self._scan_parquet()})
        if source_u == "CLICKHOUSE":
            from .clickhouse import EXCHANGE_NAME_TO_ID

            return sorted(EXCHANGE_NAME_TO_ID.keys())
        raise ValueError(f"Unknown source: {source}")

    def get_symbols(self, source: str, exchange: str | None = None) -> List[str]:
        source_u = source.upper()
        if source_u == "CSV":
            return sorted(
                {
                    i["symbol"]
                    for i in self._scan_csv()
                    if exchange is None or i["exchange"] == exchange
                }
            )
        if source_u == "PARQUET":
            return sorted(
                {
                    i["symbol"]
                    for i in self._scan_parquet()
                    if exchange is None or i["exchange"] == exchange
                }
            )
        if source_u == "CLICKHOUSE":
            return []  # symbol list not implemented
        raise ValueError(f"Unknown source: {source}")

    def get_timeframes(self, source: str) -> List[str]:
        source_u = source.upper()
        if source_u == "CSV":
            return sorted({i["timeframe"] for i in self._scan_csv()})
        if source_u == "PARQUET":
            return sorted({i["timeframe"] for i in self._scan_parquet()})
        if source_u == "CLICKHOUSE":
            from .clickhouse import INTERVAL_STR_TO_CODE

            def _conv(tf: str) -> str:
                if tf.endswith("m"):
                    return tf[:-1] + "min"
                return tf

            return sorted(_conv(tf) for tf in INTERVAL_STR_TO_CODE)
        raise ValueError(f"Unknown source: {source}")

    def get_csv_path(self, exchange: str, symbol: str, timeframe: str) -> str:
        tf_norm = timeframe.lower().replace("min", "")
        for i in self._scan_csv():
            if (
                i["exchange"].upper() == exchange.upper()
                and i["symbol"].upper() == symbol.upper()
                and i["timeframe"].lower().replace("min", "") == tf_norm
            ):
                return i["path"]
        raise FileNotFoundError(f"CSV not found for {exchange} {symbol} {timeframe}")

    def get_parquet_bar_type(self, exchange: str, symbol: str, timeframe: str) -> str:
        """Return the bar_type string matching the requested triplet."""
        tf_norm = timeframe.lower().replace("min", "")
        for i in self._scan_parquet():
            if (
                i["exchange"].upper() == exchange.upper()
                and i["symbol"].upper() == symbol.upper()
                and i["timeframe"].lower().replace("min", "") == tf_norm
            ):
                return i["bar_type"]
        raise FileNotFoundError(f"Parquet bar_type not found for {exchange} {symbol} {timeframe}")

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load(
        self,
        source: str,
        spec: Any,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Return a DataFrame with OHLCV data for the given source.

        Parameters
        ----------
        source : str
            One of ``"CSV"``, ``"PARQUET"``, or ``"CLICKHOUSE"``.
        spec : Any
            CSV → path string. PARQUET → **full** bar_type string of the
            form ``"<SYMBOL>.<VENUE>-<N>-<UNIT>-<PRICE>-<SOURCE>"`` (e.g.
            ``"BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"``). A bare instrument
            id like ``"BTCUSDT.BINANCE"`` will be rejected with
            ``ValueError`` — use :meth:`get_parquet_bar_type` to compose
            a valid bar_type from ``(exchange, symbol, timeframe)``.
            CLICKHOUSE → kwargs dict forwarded to
            :meth:`ClickHouseConnector.candles`.
        """
        source_u = source.upper()
        if source_u == "CSV":
            df = load_ohlcv_csv(spec)
        elif source_u == "PARQUET":
            if not isinstance(spec, str):
                raise TypeError("spec must be a bar_type string for PARQUET source")
            df = load_ohlcv_parquet(self._data_dir, spec)
        elif source_u == "CLICKHOUSE":
            ch = self._get_ch()
            if not isinstance(spec, dict):
                raise TypeError("spec must be dict for ClickHouse")
            return ch.candles(**spec, auto_clip=True)
        else:
            raise ValueError(f"Unknown data source: {source}")

        if (start or end) and not df.empty:
            start_dt = start or df.index[0]
            end_dt = end or df.index[-1]
            df = df.loc[start_dt:end_dt]
        return df
