# USAGE

Configuration guide for launching the dashboard against an arbitrary
NautilusTrader parquet catalog or a directory of CSV files. Covers the
environment variables wired in on `integration/workspace-setup`
(commit `608013b`) and the verified smoke-test invocation.

## 1. Quick start

### Backtest viz from a NautilusTrader parquet catalog

```bash
cd /Users/rc/Projects/workspace/nautilus-trader-streamlit
NT_DATA_DIR=/path/to/nautilus/catalog \
NT_DATA_SOURCE=PARQUET \
NT_INSTRUMENT=BTCUSDT.BINANCE \
uv run streamlit run app/main.py
```

### Backtest viz from CSV files

```bash
cd /Users/rc/Projects/workspace/nautilus-trader-streamlit
NT_DATA_DIR=/path/to/csv_dir \
NT_DATA_SOURCE=CSV \
NT_INSTRUMENT=BTCUSDT.BINANCE \
uv run streamlit run app/main.py
```

The dashboard will open on `http://localhost:8501` by default.

### Headless health probe

Use this exact invocation for scripted / CI smoke tests. This is the
command `smoker-1` verified clean in Phase 1 Task 1.7 (no tracebacks,
no warnings, 8 symbols discovered):

```bash
cd /Users/rc/Projects/workspace/nautilus-trader-streamlit
NT_DATA_DIR=/Users/rc/Projects/workspace/nautilus-trading/catalog \
NT_DATA_SOURCE=PARQUET \
NT_INSTRUMENT=BTCUSDT.BINANCE \
uv run streamlit run app/main.py \
  --server.headless=true \
  --server.port=8765 \
  --server.address=127.0.0.1 \
  --browser.gatherUsageStats=false
```

Then, from a second shell, probe Streamlit's built-in health endpoint:

```bash
curl -sf http://127.0.0.1:8765/_stcore/health
# expected: ok
```

Background the server (`&` + redirected logs) if you need the prompt
back in the same shell — see Section 5.

## 2. Environment variables reference

| Variable         | Default            | Valid values                                           | Purpose                                                               |
|------------------|--------------------|--------------------------------------------------------|-----------------------------------------------------------------------|
| `NT_DATA_DIR`    | `.`                | absolute or relative path                              | Where the dashboard looks for data (catalog root or CSV directory)    |
| `NT_DATA_SOURCE` | `CSV`              | `CSV` / `PARQUET` / `CLICKHOUSE`                       | Selects the `DataConnector` backend                                   |
| `NT_INSTRUMENT`  | `BTCUSDT.BINANCE`  | Nautilus instrument id, format `SYMBOL.VENUE`          | Which instrument the backtest runner loads and trades                 |

All three are read at startup. Changing them requires restarting
`streamlit run`. Defaults preserve upstream behaviour when the variables
are unset.

## 3. Parquet catalog layout

The `PARQUET` source loads from a NautilusTrader `ParquetDataCatalog`
directory. The loader in `modules/parquet_data.py` expects the standard
Nautilus layout:

```
<NT_DATA_DIR>/
  data/
    bar/
      <bar_type>/
        <start_ns>_<end_ns>.parquet
```

A venue-nested layout is also supported — point `NT_DATA_DIR` at either
the catalog root or a venue subdirectory:

```
<NT_DATA_DIR>/
  <venue>/            # e.g. BINANCE
    data/
      bar/
        <bar_type>/
          ...parquet
```

Parquet files use Nautilus's high-precision int128 encoding
(`fixed_size_binary[16]` scaled by `1e16`). The loader decodes this via
`pyarrow` without needing the full `nautilus_trader.persistence.catalog`
dependency. Missing directories return an empty DataFrame instead of
raising — the dashboard treats that as "no data yet".

**Direct-caller API note.** `load_ohlcv_parquet(data_dir, bar_type)`
expects a full Nautilus bar-type string like
`BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL`, not a bare instrument id.
Passing `BTCUSDT.BINANCE` silently returns an empty frame via the
missing-directory fallback. Dashboard users going through the UI do not
hit this — the `DataConnector` composes the bar type internally. If you
are importing the loader directly, use the helper:

```python
from modules.data_connector import DataConnector

conn = DataConnector(data_dir="/path/to/catalog", source="PARQUET")
bar_type = conn.get_parquet_bar_type("BINANCE", "BTCUSDT", "60min")
# -> "BTCUSDT.BINANCE-1-HOUR-LAST-EXTERNAL"
```

## 4. Supported instruments

What Phase 1 smoke tests actually exercised against the user's catalog
at `/Users/rc/Projects/workspace/nautilus-trading/catalog/`:

- **Venue:** `BINANCE`
- **Symbols:** `BTCUSDT`, `DOGEUSDT`, `ETHUSDT`, `LINKUSDT`, `NEARUSDT`, `PEPEUSDT`, `SOLUSDT`, `SUIUSDT`
- **Timeframes:** `60min` only (1-hour bars)
- **Rows per symbol:** ~8760 (one year of hourly data)

The backtest runner (`modules/backtest_runner.py`) has explicit
`TestInstrumentProvider` factory dispatch for four BINANCE pairs:
`BTCUSDT`, `ETHUSDT`, `ADAUSDT`, `ADABTC`. Any other symbol resolves
via the env var fine but falls back to the `btcusdt_binance` factory
(with a logged warning) to supply margin / tick-size parameters. This
is deliberate — adding every pair would bloat the runner for a demo
surface. See Section 6.

## 5. Common pitfalls

- **Using `csv_dir=` keyword.** Deprecated in `608013b` — the
  constructor still accepts it but emits a `DeprecationWarning`. Use
  `data_dir=` instead.
- **Passing a bare instrument id to `load_ohlcv_parquet`.** Returns an
  empty frame silently. Compose the bar type via
  `DataConnector.get_parquet_bar_type()` — see Section 3.
- **Forgetting `NT_DATA_SOURCE=PARQUET`.** The default is `CSV`, so
  pointing `NT_DATA_DIR` at a parquet catalog without flipping the
  source produces a "no data" UI. Always set both.
- **Running `streamlit run` without backgrounding.** The process
  blocks the terminal. For scripted tests, background it:
  `uv run streamlit run app/main.py ... >stream.log 2>&1 &` and
  `kill %1` when done.

## 6. Known limitations

- **ClickHouse source untested in Phase 1.** The `CLICKHOUSE` branch
  exists in `data_connector.py` but was not exercised by smoker-1 or
  builder-2. Use at your own risk until Phase 2.
- **Non-factory instruments fall back to `btcusdt_binance`.** By
  design. The runner logs a warning at startup. Pragmatic shortcut,
  not a bug — override in code if you need precise venue semantics.
- **`CSV_DEFAULT_PATH` still hardcoded.** Line 34 of
  `modules/csv_data.py` carries a legacy literal default. It only
  affects the module's `__main__` test block, not the running app
  (which reads `NT_DATA_DIR` via `DataConnector`). Left alone to
  minimise upstream merge conflict surface.

---

See also: `/Users/rc/Projects/workspace/nautilus-trading/.claude/worktrees/whimsical-churning-avalanche/plans/dashboard-integration.md` for the full Phase 1 plan and audit trail.
