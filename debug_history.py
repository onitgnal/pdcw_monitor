from datetime import UTC, datetime
from pathlib import Path
import json
import sys

import pyarrow.parquet as pq

from history import query_history

def main():
    data_dir = Path(__file__).resolve().parent / "data"
    files = sorted(data_dir.glob("*.parquet"))
    print(f"Parquet files: {[f.name for f in files]}")
    if not files:
        print("No parquet files found.")
        return
    latest = files[-1]
    print(f"Reading latest file: {latest}")
    pf = pq.ParquetFile(latest)
    tbl = pf.read()
    print(f"Total rows in file: {tbl.num_rows}")
    if tbl.num_rows == 0:
        print("File has zero rows.")
        return

    ts = tbl["ts_ms"]
    # Robust min/max for (possibly chunked) array across pyarrow versions
    try:
        import pyarrow.compute as pc
        mm = pc.min_max(ts)
        lo = int(mm["min"].as_py())
        hi = int(mm["max"].as_py())
    except Exception:
        # Fallback: combine and compute in Python
        combined = ts.combine_chunks()
        vals = combined.to_pylist()
        lo = int(min(vals))
        hi = int(max(vals))
    start_iso = datetime.fromtimestamp(lo / 1000, tz=UTC).isoformat()
    end_iso = datetime.fromtimestamp(hi / 1000, tz=UTC).isoformat()
    print(f"Timestamps range: {lo}..{hi}")
    print(f"ISO range: {start_iso} .. {end_iso}")

    # Pick a few channels that should exist
    channels = ["ADC0", "ADC1", "ADC2"]
    res = query_history(start_iso, end_iso, channels, limit=100)
    print(f"query_history returned rows: {len(res['rows'])}")
    print(f"Returned columns: {res['columns']}")
    if res["rows"]:
        print("First row:", res["rows"][0])

    # Dump a compact JSON sample (first 3 rows)
    sample = {k: (v if k != "rows" else v[:3]) for k, v in res.items()}
    print("Sample JSON:", json.dumps(sample)[:500])

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        raise
