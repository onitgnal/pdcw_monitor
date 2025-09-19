"""
PDCW Monitor
- FastAPI app serving a WS stream and modern UI
- Persistent PyFTDI reader (WinUSB) at ~10 Hz
- Daily Parquet logging with retention
"""

import asyncio
import json
import os
import struct
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pyftdi.serialext import serial_for_url

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

# ---------- Config ----------
PDCW_URL = os.getenv("PDCW_URL", "ftdi://ftdi:232:FTA1BSZM/1")
PDCW_BAUD = int(os.getenv("PDCW_BAUD", "115200"))
POLL_HZ = float(os.getenv("PDCW_HZ", "10"))  # target poll rate
READ_TIMEOUT_S = 0.30  # tight read timeout for ~10 Hz

# Channel name map (must align with device)
CHMAP: dict[int, str] = {
    **{i: f"ADC{i}" for i in range(0x0, 0xA)},
    0x0A: "CH_0A",
    0x0B: "CH_0B",
    0x0C: "CH_0C",
    0x0D: "CH_0D",
    0x0E: "CH_0E",
    0x20: "SHT75_X109_T",
    0x21: "SHT75_X109_H",
    0x22: "SHT75_X110_T",
    0x23: "SHT75_X110_H",
    0x24: "LPS22HB_AB1_T",
    0x25: "LPS22HB_AB1_P",
    0x26: "LPS22HB_AB2_T",
    0x27: "LPS22HB_AB2_P",
    0x28: "AB1_V",
    0x29: "AB1_IuA",
    0x2A: "AB2_V",
    0x2B: "AB2_IuA",
    0x2C: "AB3_V",
    0x2D: "AB3_IuA",
}

# Fixed ordered list for logging columns
CHANNELS = [
    *[f"ADC{i}" for i in range(10)],
    "CH_0A",
    "CH_0B",
    "CH_0C",
    "CH_0D",
    "CH_0E",
    "SHT75_X109_T",
    "SHT75_X109_H",
    "SHT75_X110_T",
    "SHT75_X110_H",
    "LPS22HB_AB1_T",
    "LPS22HB_AB1_P",
    "LPS22HB_AB2_T",
    "LPS22HB_AB2_P",
    "AB1_V",
    "AB1_IuA",
    "AB2_V",
    "AB2_IuA",
    "AB3_V",
    "AB3_IuA",
]


# ---------- Low-level PDCW I/O ----------
def _decode_packet(payload: bytes) -> dict[str, float]:
    """Decode the PDCW binary payload (big-endian floats for channel values)."""
    off = 0
    _trig = struct.unpack_from("<I", payload, off)[0]
    off += 4
    _gpio = struct.unpack_from("<H", payload, off)[0]
    off += 2
    nch = struct.unpack_from("<B", payload, off)[0]
    off += 1
    values: dict[str, float] = {}
    for _ in range(nch):
        ch = payload[off]
        off += 1
        _stat = payload[off]
        off += 1  # status unused
        val = struct.unpack_from(">f", payload, off)[0]
        off += 4  # BIG-ENDIAN float
        name = CHMAP.get(ch, f"CH_{ch:02X}")
        values[name] = float(val)
    return values


def _read_values_from(ser) -> dict[str, float]:
    """Send ?c.v and read one packet from an already-open serial handle."""
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
    except Exception:
        pass

    ser.write(b"?c.v\r\n")
    ser.flush()

    # Header byte
    start = ser.read(1)
    if start != b"*":
        junk = (start or b"") + ser.read(64)
        raise RuntimeError(f"Unexpected start: {junk!r}")

    # 2-byte length (prefer sane BE if LE looks huge)
    len_bytes = ser.read(2)
    if len(len_bytes) != 2:
        raise RuntimeError("Timeout waiting for length")
    plen_le = struct.unpack("<H", len_bytes)[0]
    plen_be = struct.unpack(">H", len_bytes)[0]
    plen = plen_be if (0 < plen_be < 4096 and not (0 < plen_le < 4096)) else plen_le

    # Payload
    payload = bytearray()
    while len(payload) < plen:
        chunk = ser.read(plen - len(payload))
        if not chunk:
            raise RuntimeError(f"Timeout reading payload ({len(payload)}/{plen})")
        payload.extend(chunk)

    # Do NOT block on optional CRLF trailer
    return _decode_packet(bytes(payload))


# ---------- Background reader (persistent FTDI handle) ----------
class PdcwReader:
    """Opens FTDI once and streams at POLL_HZ without blocking on trailers."""

    def __init__(
        self, url: str, baud: int, loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[dict]"
    ):
        self.url, self.baud = url, baud
        self.loop, self.queue = loop, queue
        self._stop = threading.Event()
        self._th: threading.Thread | None = None

    def start(self):
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, name="PDCW-Reader", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th and self._th.is_alive():
            self._th.join(timeout=2)

    def _run(self):
        period = max(0.001, 1.0 / max(0.1, POLL_HZ))
        with serial_for_url(
            self.url, baudrate=self.baud, timeout=READ_TIMEOUT_S, write_timeout=READ_TIMEOUT_S
        ) as ser:
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass
            while not self._stop.is_set():
                t0 = time.time()
                try:
                    vals = _read_values_from(ser)
                    sample = {"ts": int(time.time() * 1000), "values": vals}
                    asyncio.run_coroutine_threadsafe(self.queue.put(sample), self.loop)
                except Exception as e:
                    err = {"ts": int(time.time() * 1000), "error": str(e)}
                    asyncio.run_coroutine_threadsafe(self.queue.put(err), self.loop)
                    time.sleep(0.2)  # small backoff
                dt = time.time() - t0
                if dt < period:
                    time.sleep(period - dt)


# ---------- Parquet logger (daily rotate, batched writes, retention) ----------
class ParquetLogger:
    """
    Efficient long-term logger:
      - writes Parquet with zstd compression (float32 columns)
      - one file per day; on restart creates a new suffixed file if today's exists
      - buffered writes (flush_every rows)
      - retention policy by days (deletes old daily files)
    """

    def __init__(self, root: Path, retention_days: int = 14, flush_every: int = 500):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.flush_every = flush_every
        self._buf: list[list] = []  # rows: [ts_ms, ch1, ch2, ...]
        self._writer: pq.ParquetWriter | None = None
        self._open_day: str | None = None
        self._open_path: Path | None = None
        # schema: ts_ms int64 + float32 columns (NaN allowed)
        fields = [pa.field("ts_ms", pa.int64())] + [pa.field(c, pa.float32()) for c in CHANNELS]
        self._schema = pa.schema(fields)

    def _day_key(self, ts_ms: int) -> str:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone()
        return dt.strftime("%Y-%m-%d")

    def _unique_daily_path(self, day_key: str) -> Path:
        base = self.root / f"{day_key}.parquet"
        if not base.exists():
            return base
        # find a free suffix
        n = 1
        while True:
            cand = self.root / f"{day_key}_{n}.parquet"
            if not cand.exists():
                return cand
            n += 1

    def _ensure_writer(self, day_key: str):
        if self._writer and self._open_day == day_key:
            return
        # rotate/close previous
        if self._writer:
            self._flush()
            self._writer.close()
            self._writer = None
        path = self._unique_daily_path(day_key)
        self._writer = pq.ParquetWriter(
            where=str(path),
            schema=self._schema,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        self._open_day = day_key
        self._open_path = path
        self._prune_old()

    def _flush(self):
        if not self._buf or not self._writer:
            return
        cols = list(zip(*self._buf, strict=False))  # transpose rows->columns
        arrays = [pa.array(cols[0], type=pa.int64())]  # ts_ms
        for i, _name in enumerate(CHANNELS, start=1):
            arrays.append(pa.array(cols[i], type=pa.float32()))
        table = pa.Table.from_arrays(arrays, names=["ts_ms", *CHANNELS])
        self._writer.write_table(table)
        self._buf.clear()

    def _prune_old(self):
        if self.retention_days <= 0:
            return
        cutoff = datetime.now().date() - timedelta(days=self.retention_days)
        for p in self.root.glob("*.parquet"):
            try:
                stem = p.stem  # e.g. 2025-09-19 or 2025-09-19_1
                day = stem.split("_", 1)[0]
                dt = datetime.strptime(day, "%Y-%m-%d").date()
                if dt < cutoff:
                    p.unlink(missing_ok=True)
            except Exception:
                continue

    def handle(self, sample: dict):
        if "values" not in sample:
            return
        ts = int(sample["ts"])
        vals = sample["values"]
        row = [ts] + [float(vals.get(name, float("nan"))) for name in CHANNELS]
        day_key = self._day_key(ts)
        self._ensure_writer(day_key)
        self._buf.append(row)
        if len(self._buf) >= self.flush_every:
            self._flush()

    def close(self):
        try:
            self._flush()
        finally:
            if self._writer:
                self._writer.close()
                self._writer = None


# ---------- FastAPI app + WebSocket broadcast ----------
app = FastAPI(title="PDCW Monitor", version="1.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    idx = STATIC_DIR / "index.html"
    if not idx.exists():
        return HTMLResponse(
            "<h1>PDCW Monitor</h1><p><code>static/index.html</code> is missing.</p>",
            status_code=200,
        )
    return FileResponse(str(idx))


class Hub:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def add(self, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.clients.add(ws)

    async def remove(self, ws: WebSocket):
        async with self.lock:
            self.clients.discard(ws)

    async def broadcast(self, message: dict):
        data = json.dumps(message)
        dead: list[WebSocket] = []
        async with self.lock:
            for ws in list(self.clients):
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.append(ws)
            for d in dead:
                self.clients.discard(d)


hub = Hub()
queue: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=32)
reader: PdcwReader | None = None
logger: ParquetLogger | None = None


@app.on_event("startup")
async def _on_start():
    global reader, logger
    loop = asyncio.get_event_loop()
    reader = PdcwReader(PDCW_URL, PDCW_BAUD, loop, queue)
    reader.start()
    logger = ParquetLogger(DATA_DIR, retention_days=14, flush_every=500)
    asyncio.create_task(_broadcaster())


@app.on_event("shutdown")
async def _on_stop():
    if reader:
        reader.stop()
    if logger:
        logger.close()


async def _broadcaster():
    while True:
        msg = await queue.get()
        await hub.broadcast(msg)
        if logger and isinstance(msg, dict) and "values" in msg:
            logger.handle(msg)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.add(ws)
    try:
        meta = {"ts": int(time.time() * 1000), "meta": {"channels": list(CHANNELS)}}
        await ws.send_text(json.dumps(meta))
        while True:
            await ws.receive_text()  # client pings; broadcasting is independent
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=5001, reload=False)
