# PDCW Monitor

A small FastAPI web app that talks to a PDCW device over **FTDI/WinUSB** via **PyFTDI**, streams values at ~10 Hz, plots a rolling history, and logs long-term data to **Parquet**.

## Features
- 10 Hz polling with a persistent FTDI handle (fast, low overhead)
- Live WebSocket stream to the browser
- Left panel: channel list + live values; Right: rolling Plotly chart
- “Window” control; “Clear” safely resets traces
- Daily Parquet logging (`data/YYYY-MM-DD*.parquet`) with zstd compression
- CLI: `pdcw_cli.py set-avg/get-avg/get-values`
- Export time ranges from history to CSV: `export_range.py`

## Requirements
- Windows host with the PDCW connected via an FTDI USB cable using **WinUSB/libusb**
- Python (managed by `pixi`)
- Browser (Chrome/Edge/Firefox)

## Setup

```powershell
pixi install
```

## Run (port 5001)
```powershell
# Optional: choose polling rate (Hz)
$env:PDCW_HZ = 10

pixi run web
# or
pixi run dev
```

Open: `http://<host>:5001`

## Configuration (env vars)
- `PDCW_URL`  (default `ftdi://ftdi:232:FTA1BSZM/1`)
- `PDCW_BAUD` (default `115200`)
- `PDCW_HZ`   (default `10`)

## Project Layout
```
.
├─ app.py                # FastAPI app + reader + parquet logger
├─ pdcw_cli.py           # CLI to set/get averaging & dump values
├─ export_range.py       # Export history range to ASCII
├─ pixi.toml             # env + tasks
├─ static/
│  ├─ index.html
│  ├─ styles.css
│  └─ main.js
└─ data/                 # daily parquet files (created at runtime)
```

## Long-term logging
- One Parquet file per day in `data/` (zstd, float32 columns).
- Retention defaults to **14 days** (change in `app.py` → `ParquetLogger`).
- Read with Pandas/Polars/Arrow:
  ```python
  import pandas as pd
  df = pd.read_parquet('data/2025-09-19.parquet')
  ```

## CLI examples
```powershell
python .\pdcw_cli.py get-avg
python .\pdcw_cli.py set-avg 16
python .\pdcw_cli.py get-values
```

## Export history to CSV
```powershell
python .\export_range.py --start "2025-09-19T12:00:00+02:00" --end "2025-09-19T12:05:00+02:00" --out out.csv --sep "," --channels ADC0 LPS22HB_AB1_P
```

## Development
Format & lint:
```powershell
pixi run fmt
pixi run lint
```

Pre-commit hooks (optional):
```powershell
pixi run hooks-install
```

## Troubleshooting
- **Slow updates** → ensure fast `app.py` (persistent FTDI, `READ_TIMEOUT_S ≤ 0.30`) and low averaging (e.g., 16).
- **Web app blank** → confirm `static/index.html` exists and app runs from project root.
- **WinUSB vs COM** → we use PyFTDI over WinUSB (no COM port needed).
