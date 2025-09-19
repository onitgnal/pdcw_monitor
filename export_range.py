"""
Export a time span from Parquet history (data/*.parquet) to an ASCII file.

Usage:
  python export_range.py \\
    --start "2025-09-19T12:00:00+02:00" \\
    --end "2025-09-19T12:05:00+02:00" \\
    --out out.csv --sep "," \\
    --channels ADC0 ADC1 LPS22HB_AB1_P
Notes:
  - Reads daily Parquet files created by app.py (columns: ts_ms + channels).
  - Writes header: ts_iso, ts_ms, <channels...>
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def iso_to_ms(s: str) -> int:
    # Accept 'Z' → UTC
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def main():
    ap = argparse.ArgumentParser(description="Export a time range from Parquet history to ASCII")
    ap.add_argument("--data-dir", default="data", help="Folder containing daily parquet files")
    ap.add_argument(
        "--start", required=True, help='Start time (ISO 8601), e.g. "2025-09-19T12:00:00+02:00"'
    )
    ap.add_argument(
        "--end", required=True, help='End time (ISO 8601), e.g. "2025-09-19T12:05:00+02:00"'
    )
    ap.add_argument("--out", required=True, help="Output ASCII file (CSV/TSV based on --sep)")
    ap.add_argument("--sep", default=",", help='Delimiter, default ","; use "\\t" for TSV')
    ap.add_argument(
        "--channels",
        nargs="*",
        default=[],
        help="Subset of channel columns to export; default = all",
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

    # Minimum columns to read
    read_cols = ["ts_ms"]
    if args.channels:
        read_cols += args.channels  # trust caller to name channels correctly

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wrote_header = False
    sep = args.sep.encode("utf-8").decode("unicode_escape")  # allow "\t"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=sep)
        for p in files:
            pf = pq.ParquetFile(p)
            for batch in pf.iter_batches(columns=None if not args.channels else read_cols):
                tbl = pa.Table.from_batches([batch])
                # Ensure ts_ms exists
                if "ts_ms" not in tbl.column_names:
                    continue
                # Filter by time range
                mask = pc.and_(
                    pc.greater_equal(tbl["ts_ms"], pa.scalar(start_ms, pa.int64())),
                    pc.less(tbl["ts_ms"], pa.scalar(end_ms, pa.int64())),
                )
                filtered = tbl.filter(mask)
                if filtered.num_rows == 0:
                    continue

                # Decide export columns & header
                export_cols = ["ts_ms"] + [c for c in filtered.column_names if c != "ts_ms"]
                if not wrote_header:
                    writer.writerow(["ts_iso"] + export_cols)  # ts_iso first for readability
                    wrote_header = True

                # Convert to rows; add ts_iso
                cols_dict = {name: filtered[name].to_pylist() for name in export_cols}
                for i in range(len(cols_dict["ts_ms"])):
                    ts_ms = int(cols_dict["ts_ms"][i])
                    row = [ms_to_iso(ts_ms)] + [cols_dict[name][i] for name in export_cols]
                    writer.writerow(row)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
