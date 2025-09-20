from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DATA_DIR = Path(__file__).resolve().parent / "data"

def iso_to_ms(s: str) -> int:
    """Convert ISO 8601 string to UTC milliseconds."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return int(dt.timestamp() * 1000)

def query_history(start_iso: str, end_iso: str, channels: list[str], limit: int) -> dict:
    """
    Query historical data from Parquet files, with downsampling.

    Returns a dictionary with "columns" and "rows".
    """
    start_ms = iso_to_ms(start_iso)
    end_ms = iso_to_ms(end_iso)

    if not DATA_DIR.exists():
        return {"columns": [], "rows": []}

    files = sorted(DATA_DIR.glob("*.parquet"))
    if not files:
        return {"columns": [], "rows": []}

    # Always include ts_ms for filtering and the x-axis
    read_cols = ["ts_ms"] + [c for c in channels if c != "ts_ms"]

    all_tables = []
    for p in files:
        try:
            pf = pq.ParquetFile(p)
            # Check if the file's metadata indicates it might contain relevant data
            if pf.metadata.num_rows == 0:
                continue

            # This is a basic check; a more robust solution might check row group stats
            # For now, we read the file if its name suggests it's in the date range
            # (A more advanced implementation would parse dates from filenames)

            for batch in pf.iter_batches(columns=read_cols):
                tbl = pa.Table.from_batches([batch])
                if "ts_ms" not in tbl.column_names:
                    continue

                mask = pc.and_(
                    pc.greater_equal(tbl["ts_ms"], pa.scalar(start_ms, pa.int64())),
                    pc.less_equal(tbl["ts_ms"], pa.scalar(end_ms, pa.int64())),
                )
                filtered = tbl.filter(mask)
                if filtered.num_rows > 0:
                    all_tables.append(filtered)
        except Exception:
            # Ignore corrupted or unreadable files
            continue

    if not all_tables:
        return {"columns": ["ts_iso"] + channels, "rows": []}

    full_table = pa.concat_tables(all_tables)
    if full_table.num_rows == 0:
        return {"columns": ["ts_iso"] + channels, "rows": []}

    # Sort by timestamp
    full_table = full_table.sort_by([("ts_ms", "ascending")])

    # Downsample if necessary
    if full_table.num_rows > limit:
        step = full_table.num_rows // limit
        indices = pa.array(range(0, full_table.num_rows, step))
        sampled_table = full_table.take(indices)
    else:
        sampled_table = full_table

    # Format for JSON output
    output_cols = ["ts_ms"] + [c for c in channels if c in sampled_table.column_names]

    # Convert to list of rows for the final output
    rows = []
    col_data = {name: sampled_table[name].to_pylist() for name in output_cols}

    for i in range(len(col_data["ts_ms"])):
        ts_ms = col_data["ts_ms"][i]
        # Convert timestamp to ISO string for the first column
        ts_iso = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).isoformat()
        row = [ts_iso] + [col_data[name][i] for name in output_cols[1:]]
        rows.append(row)

    # Final column headers, with ts_iso first
    final_columns = ["ts_iso"] + output_cols[1:]

    return {"columns": final_columns, "rows": rows}
