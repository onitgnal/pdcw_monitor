"""
Export a time span from Parquet history (data/*.parquet) to an ASCII (CSV/TSV) file.

Usage:
  python export_range.py \\
    --start "2025-09-19T12:00:00+02:00" \\
    --end "2025-09-19T12:05:00+02:00" \\
    --out out.csv --sep "," \\
    --channels ADC0 ADC1 LPS22HB_AB1_P \\
    --with-ms

Notes:
  - Reads daily Parquet files created by app.py (columns: ts_ms + channels).
  - Default output header now: ts_iso,<channel1>,<channel2>,...
    (one dedicated column per channel; numeric ts_ms only included if --with-ms)
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import List

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

def iso_to_ms(s: str) -> int:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return int(dt.timestamp() * 1000)

def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()

def determine_channel_order(available: List[str]) -> List[str]:
    """
    Return a stable channel ordering based on app.CHANNELS if available,
    filtered to those present in the Parquet batch. Fallback to sorted.
    """
    try:
        from app import CHANNELS as APP_CHANNELS  # noqa
        ordered = [c for c in APP_CHANNELS if c in available]
        # Include any extra columns (unexpected) at the end in sorted order
        extra = sorted([c for c in available if c not in APP_CHANNELS and c != "ts_ms"])
        return ordered + extra
    except Exception:
        return [c for c in available if c != "ts_ms"]

def main():
    ap = argparse.ArgumentParser(description="Export a time range from Parquet history to ASCII (wide format)")
    ap.add_argument("--data-dir", default="data", help="Folder containing daily parquet files")
    ap.add_argument("--start", required=True, help='Start time (ISO 8601), e.g. "2025-09-19T12:00:00+02:00"')
    ap.add_argument("--end", required=True, help='End time (ISO 8601), e.g. "2025-09-19T12:05:00+02:00"')
    ap.add_argument("--out", required=True, help="Output ASCII file (CSV/TSV based on --sep)")
    ap.add_argument("--sep", default=",", help='Delimiter, default ","; use "\\t" for TSV')
    ap.add_argument(
        "--channels",
        nargs="*",
        default=[],
        help="Subset of channel columns to export; default = all channels present",
    )
    ap.add_argument(
        "--with-ms",
        action="store_true",
        help="Include numeric ts_ms column after ts_iso",
    )
    args = ap.parse_args()

    start_ms = iso_to_ms(args.start)
    end_ms = iso_to_ms(args.end)
    if end_ms <= start_ms:
        raise SystemExit("end must be > start")

    data_dir = Path(args.data_dir)
    files = sorted(data_dir.glob("*.parquet"))
    if not files:
        raise SystemExit(f"No parquet files in {data_dir}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sep = args.sep.encode("utf-8").decode("unicode_escape")  # allow "\t"
    wrote_header = False
    channel_cols: list[str] = []

    total_rows_written = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=sep)

        for p in files:
            pf = pq.ParquetFile(p)
            # Read all columns if user did not restrict; else only required subset
            iter_cols = None if not args.channels else ["ts_ms", *args.channels]
            for batch in pf.iter_batches(columns=iter_cols):
                tbl = pa.Table.from_batches([batch])
                if "ts_ms" not in tbl.column_names:
                    continue

                # Filter by time
                mask = pc.and_(
                    pc.greater_equal(tbl["ts_ms"], pa.scalar(start_ms, pa.int64())),
                    pc.less(tbl["ts_ms"], pa.scalar(end_ms, pa.int64())),
                )
                filtered = tbl.filter(mask)
                if filtered.num_rows == 0:
                    continue

                # Determine channel columns once (excluding ts_ms)
                if not wrote_header:
                    available = [c for c in filtered.column_names if c != "ts_ms"]
                    if args.channels:
                        # Preserve user order but only keep those actually present
                        channel_cols = [c for c in args.channels if c in available]
                    else:
                        channel_cols = determine_channel_order(available)
                    header = ["ts_iso"]
                    if args.with_ms:
                        header.append("ts_ms")
                    header.extend(channel_cols)
                    writer.writerow(header)
                    wrote_header = True

                # Build dictionary of needed columns
                cols_needed = ["ts_ms", *channel_cols]
                cols_dict = {name: filtered[name].to_pylist() for name in cols_needed}

                ts_list = cols_dict["ts_ms"]
                for i, ts_val in enumerate(ts_list):
                    ts_ms = int(ts_val)
                    row = [ms_to_iso(ts_ms)]
                    if args.with_ms:
                        row.append(ts_ms)
                    # Channel values (may be missing -> append None / NaN)
                    for ch in channel_cols:
                        arr = cols_dict.get(ch)
                        if arr is None:
                            row.append("")
                        else:
                            v = arr[i]
                            row.append(v)
                    writer.writerow(row)
                    total_rows_written += 1

    if not wrote_header:
        print("No rows matched the specified time range.")
    else:
        print(f"Wrote {total_rows_written} rows to {out_path}")

if __name__ == "__main__":
    main()
