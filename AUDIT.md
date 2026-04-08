# AUDIT.md — nautilus_trader_streamlit Repo Inventory
> Phase 1 Task 1.4 — produced by auditor-1, 2026-04-08

---

## 1. Entry Point(s)

**Primary entry point:** `app/main.py`

Launch command per README:
```bash
pip install -r requirements.txt
streamlit run app/main.py
```

- No CLI arguments are accepted by the app itself (Streamlit standard)
- `app/main.py` appends `pathlib.Path(__file__).resolve().parents[1]` to `sys.path` at line 34, so it can be run from any working directory
- Strategy discovery: `discover_strategies("strategies")` at line 1509 scans `strategies/*.py` from CWD; falls back to `.` if the folder is missing
- No Makefile in the repo — only README quick-start

---

## 2. Dependencies

### Full `requirements.txt` (verbatim)

```
-i https://packages.nautechsystems.io/simple
--extra-index-url https://pypi.org/simple
--only-binary=nautilus-trader

wheel
streamlit
pandas
numpy
plotly
nautilus_trader
clickhouse-driver
python-dotenv
streamlit-lightweight-charts-v5>=0.1.7
extra-streamlit-components
```

### Key observations

| Package | Version declared | Notes |
|---|---|---|
| `nautilus_trader` | **unpinned** | Pulled from `https://packages.nautechsystems.io/simple` binary-only. Will resolve to latest available. |
| `streamlit` | unpinned | |
| `pandas` | unpinned | |
| `numpy` | unpinned | |
| `plotly` | unpinned | |
| `pyarrow` | **not listed** | Not a direct dep, but NautilusTrader pulls it transitively |
| `streamlit-lightweight-charts-v5` | `>=0.1.7` | Only lower-bound pin |
| `clickhouse-driver` | unpinned | Used for experimental ClickHouse source only |
| `python-dotenv` | unpinned | |
| `extra-streamlit-components` | unpinned | Tab widget; imported with `try/except` fallback |

**nautilus_trader version risk:** No version pin exists. The `--only-binary=nautilus-trader` flag forces wheel resolution from `packages.nautechsystems.io`. Whatever version is current there may differ from v1.224.0. Task 1.5 must pin `nautilus_trader==1.224.0` (or `>=1.224.0,<2`) in the generated `pyproject.toml`.

**ML dependencies:** None currently installed (v0.4 roadmap mentions Qlib/skfolio but they are NOT in `requirements.txt`). This repo is purely a viz/backtest runner — escalation criterion not triggered.

---

## 3. Data Loaders

### Architecture

| Module | Role |
|---|---|
| `modules/csv_data.py` | Low-level CSV reader → `pd.DataFrame` |
| `modules/data_connector.py` | Unified facade: CSV or ClickHouse |
| `modules/backtest_runner.py` | DataFrame → Nautilus `Bar` objects via `BarDataWrangler` |

### File formats

- **Accepts:** CSV only (via `DataConnector(source="CSV")`)
- **ClickHouse:** secondary source, experimental/unstable
- **Parquet / ParquetDataCatalog:** **not supported** — no import, no reader

### CSV schema expected by `load_ohlcv_csv()`

| Column | Required | Type | Notes |
|---|---|---|---|
| `timestamp` / `time` / `date` | Yes | numeric (ns/us/ms/s) or string | Auto-detected unit |
| `open` | Yes | float64 | |
| `high` | Yes | float64 | |
| `low` | Yes | float64 | |
| `close` | Yes | float64 | |
| `volume` | No | float64 | Optional |

The index becomes a `DatetimeIndex` (UTC). This schema exactly matches what NautilusTrader's `BarDataWrangler.process(df)` expects.

### CSV file discovery

`DataConnector(csv_dir=".")` scans `csv_dir` for filenames matching:

```python
re.compile(r"(?P<ex>[A-Z]+)_(?P<sym>[A-Z]+),\s*(?P<tf>\d+)\.csv")
```

**Examples matched:** `BINANCE_BTCUSD, 1.csv`, `BINANCE_BTCUSD, 15.csv`

The `csv_dir` is **not configurable** from outside the app today — it defaults to CWD `"."`. This is the primary externalization target for Task 1.6.

### Hardcoded path for the test runner

`modules/csv_data.py:34`:
```python
CSV_DEFAULT_PATH = "BINANCE_BTCUSD, 15.csv"
```
This is only used in `if __name__ == "__main__"` — not in the live app flow. Low risk but worth noting.

### Critical gap: no ParquetDataCatalog reader

The app has **zero code** to read from a `ParquetDataCatalog`. User's `catalog/` directory (parquet) cannot be fed directly. Task 1.6 must either:
- (a) Add a parquet data loader that reads `catalog/<instrument>/bars-*.parquet` and converts to the expected schema, OR
- (b) Export the catalog to CSV as a pre-processing step

---

## 4. Chart Rendering

### Libraries used

| Library | Purpose |
|---|---|
| `streamlit-lightweight-charts-v5` (`lwc`) | Price/candlestick chart (main OHLCV view) |
| `plotly` (`px`, `go`) | Equity curve, drawdown, trade distributions, analytics |

### File

All rendering is in `app/main.py` via `draw_dashboard()` starting around line 234.

### Price chart (`lwc`)

- Renders candlestick or line chart
- Supports **volume bars** (optional toggle)
- Supports **cumulative PnL overlay**
- Supports **trade entry/exit markers**
- Supports **50 SMA** and **21 EMA** overlays (checkboxes at lines 852-853)
- Falls back with an error if `streamlit-lightweight-charts-v5` is not installed

### Plotly charts

- Equity curve (`fig_eq`)
- Drawdown (`fig_dd`)
- Trade profit histogram
- Rolling Sharpe/Sortino
- Weekly/hourly PnL heatmaps
- Comparative analysis charts

---

## 5. Nautilus-Specific Integration

### Imports from `nautilus_trader`

| Import | File | Purpose |
|---|---|---|
| `BacktestEngine` | `modules/backtest_runner.py:11` | Runs the backtest |
| `StrategyConfig` | `modules/backtest_runner.py:12` | Base config class |
| `BarSpecification`, `BarType` | `modules/backtest_runner.py:13` | Bar type construction |
| `BTC`, `USDT` | `modules/backtest_runner.py:14` | Currency objects |
| `AggregationSource`, `AccountType`, `BarAggregation`, `OmsType`, `PriceType` | `modules/backtest_runner.py:15-21` | Engine config enums |
| `Venue` | `modules/backtest_runner.py:23` | Venue identifier |
| `Money` | `modules/backtest_runner.py:24` | Starting balance |
| `BarDataWrangler` | `modules/backtest_runner.py:26` | DataFrame → Bar objects |
| `TestInstrumentProvider` | `modules/backtest_runner.py:27` | Instrument factory |
| `Strategy` | `modules/backtest_runner.py:28` | Strategy base class |
| `Actor` | `modules/dashboard_actor.py:19` | DashboardPublisher actor |
| `Strategy`, `StrategyConfig` | `modules/strategy_loader.py:8-9` | Strategy discovery |

### ParquetDataCatalog

**Not used.** The app does not import `nautilus_trader.persistence.catalog.ParquetDataCatalog` anywhere.

### Data source agnosticism

The backtest runner is exchange-agnostic at the DataFrame level — it accepts any OHLCV DataFrame. However, `_init_engine()` hardcodes `Venue("BINANCE")` and `TestInstrumentProvider.btcusdt_binance()`, meaning only BTCUSDT/BINANCE is supported without code changes.

### Assumption about data source

The app assumes data comes from CSV files co-located with (or near) the app. It does **not** assume data is a NautilusTrader backtest output — it re-runs the backtest internally from scratch using its own bundled strategies.

---

## 6. Hardcoded Paths Scan

Command run: `rg -n '/catalog|/data|/Users|~/|\./data|\./catalog' --type py` from repo root.

**Results: zero matches for absolute paths.**

Only hardcoded data reference found:

| File | Line | Content |
|---|---|---|
| `modules/csv_data.py` | 34 | `CSV_DEFAULT_PATH = "BINANCE_BTCUSD, 15.csv"` |

This is a relative path used only in the `__main__` test runner block, not in the Streamlit app. The live app resolves CSV paths via `DataConnector(csv_dir=".")` which defaults to the process working directory.

**Externalization targets for Task 1.6:**

1. `DataConnector(csv_dir=".")` in `app/main.py:1521` and `app/main.py:1686` — should become `DataConnector(csv_dir=os.getenv("NT_DATA_DIR", "."))` or accept a `--data-dir` CLI flag passed via `streamlit run app/main.py -- --data-dir /path`
2. `CSV_DEFAULT_PATH` in `modules/csv_data.py:34` — low priority (test only), but should reference `NT_DATA_DIR` for consistency

---

## 7. Risks

### Risk 1 — nautilus_trader version mismatch (HIGH — POTENTIAL BLOCKER for Task 1.5)

`requirements.txt` has no version pin on `nautilus_trader`. The index is `packages.nautechsystems.io` with `--only-binary`. The user's project pins `v1.224.0`. Task 1.5 must:
- Add `nautilus-trader==1.224.0` (note: package name uses hyphen, not underscore) to `pyproject.toml`
- Keep the `--only-binary` flag and the nautechsystems index URL as a uv extra index
- Verify that `1.224.0` is available as a binary wheel on that index for the target Python version (3.13)

The API imports (`BacktestEngine`, `BarDataWrangler`, `TestInstrumentProvider`, `trader.generate_order_fills_report()`) are all present in v1.224.0 based on the user's main project using the same API. No escalation needed, but Task 1.5 must pin explicitly.

### Risk 2 — No ParquetDataCatalog support (HIGH — AFFECTS Task 1.6 scope)

The upstream app reads CSV only. User's backtest catalog at `catalog/` stores parquet files written by NautilusTrader's `ParquetDataCatalog`. Connecting the dashboard to real catalog data requires one of:
- A new `parquet_data.py` module that reads `catalog/<instrument>/bars-*.parquet` → DataFrame in the expected OHLCV schema
- A `DataConnector` source type `"PARQUET"` that wraps this loader
- Or pre-export of parquet → CSV (lossy/slow for large catalogs)

This is an expansion of Task 1.6 scope beyond the originally scoped "env var + CLI flag" work. Recommend the team-lead decide whether to extend 1.6 or create a new sub-task (1.6b) for the parquet adapter.

### Risk 3 — Instrument provider hardcoded to BTCUSDT/BINANCE (MEDIUM)

`TestInstrumentProvider.btcusdt_binance()` is hardcoded in `modules/backtest_runner.py`. The user's project trades 8+ crypto pairs. To support other instruments, a mapping from CSV exchange+symbol → instrument provider factory is needed.

### Risk 4 — CWD-relative CSV scanning (LOW — covered by Task 1.6)

`DataConnector(csv_dir=".")` scans the process CWD. If `streamlit run app/main.py` is launched from a different directory, no CSVs will be found. Task 1.6 env var externalization resolves this.

### Risk 5 — extra-streamlit-components / lightweight-charts optional imports (LOW)

Both are imported with `try/except`. If not installed, the app degrades gracefully (tab widget falls back to plain select, price chart shows error). No runtime crash risk, but UX degrades noticeably without them.

### Risk 6 — Python 3.13 wheel availability (UNKNOWN)

The repo declares no Python version. User's project uses Python 3.13. Verify that `nautilus-trader==1.224.0` binary wheel exists for Python 3.13 on `packages.nautechsystems.io`. If not, Task 1.5 may need to target Python 3.12.

---

## Summary Table

| Check | Finding |
|---|---|
| nautilus_trader version pin | **None** — must add `==1.224.0` in Task 1.5 |
| ML dependencies | **None** — purely viz/backtest runner |
| ParquetDataCatalog support | **Absent** — CSV-only; Task 1.6 scope must grow |
| Absolute hardcoded paths | **None found** |
| Entry point | `streamlit run app/main.py` |
| Chart libs | Lightweight Charts v5 (price) + Plotly (analytics) |
| Instrument support | BTCUSDT/BINANCE hardcoded in backtest runner |
