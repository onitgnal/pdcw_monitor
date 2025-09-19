# pdcw_cli.py — resilient CLI for PDCW over PyFTDI (WinUSB)
import argparse
import binascii
import struct
import sys
import time
from contextlib import suppress

from pyftdi.serialext import serial_for_url

DEFAULT_URL = "ftdi://ftdi:232:FTA1BSZM/1"
DEFAULT_BAUD = 115200

CHMAP = {
    **{i: f"ADC{i}" for i in range(0x0, 0xA)},  # ADC0..ADC9
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


def open_ser(url, baud, timeout):
    ser = serial_for_url(url, baudrate=baud, timeout=timeout, write_timeout=timeout)
    with suppress(Exception):
        ser.reset_input_buffer()
        ser.reset_output_buffer()
    time.sleep(0.05)
    return ser


def send_line(ser, line: bytes):
    if not line.endswith(b"\r\n"):
        line += b"\r\n"
    ser.write(line)
    ser.flush()


def read_line_retry(ser, tag="line", retries=3, delay=0.15):
    for _ in range(retries):
        line = ser.readline()
        if line:
            return line
        time.sleep(delay)
        with suppress(Exception):
            ser.reset_input_buffer()
    raise RuntimeError(f"Timeout waiting for {tag}")


def get_avg(url, baud, timeout):
    with open_ser(url, baud, timeout) as ser:
        send_line(ser, b"?c.a")
        resp = read_line_retry(ser, "avg")
        print(resp.decode(errors="replace").strip())


def set_avg(url, baud, timeout, n):
    with open_ser(url, baud, timeout) as ser:
        with suppress(Exception):
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        send_line(ser, f"!c.a={n}".encode())
        ack = read_line_retry(ser, "set-ack")
        print("SET:", ack.decode(errors="replace").strip())
        time.sleep(0.15)
        with suppress(Exception):
            ser.reset_input_buffer()
        send_line(ser, b"?c.a")
        got = read_line_retry(ser, "avg")
        print("GET:", got.decode(errors="replace").strip())


def parse_packet(payload: bytes):
    off = 0
    trig = struct.unpack_from("<I", payload, off)[0]
    off += 4
    gpio = struct.unpack_from("<H", payload, off)[0]
    off += 2
    nch = struct.unpack_from("<B", payload, off)[0]
    off += 1
    print(f"Header: Trigger={trig} GPIO=0x{gpio:04X} Channels={nch}")
    for i in range(nch):
        ch = payload[off]
        off += 1
        status = payload[off]
        off += 1
        val = struct.unpack_from(">f", payload, off)[0]
        off += 4  # big-endian float
        name = CHMAP.get(ch, f"CH_{ch:02X}")
        if name.endswith("_T"):
            disp = f"{val:.2f} °C"
        elif name.endswith("_H"):
            disp = f"{val:.2f} %RH"
        elif name.endswith("_P"):
            disp = f"{val:.2f} hPa"
        elif name.endswith("_V"):
            disp = f"{val:.4f} V"
        elif name.endswith("_IuA"):
            disp = f"{val:.2f} µA"
        else:
            disp = f"{val:.6g}"
        print(f"{i:02d}: {name:14s} (0x{ch:02X}) status=0x{status:02X} value={disp}")


def get_values(url, baud, timeout):
    with open_ser(url, baud, timeout) as ser:
        send_line(ser, b"?c.v")
        start = ser.read(1)
        if start != b"*":
            junk = (start or b"") + ser.read(64)
            print("Unexpected start:", repr(junk))
            sys.exit(1)
        len_bytes = ser.read(2)
        if len(len_bytes) != 2:
            raise RuntimeError("Timeout waiting for length")
        plen_le = struct.unpack("<H", len_bytes)[0]
        plen_be = struct.unpack(">H", len_bytes)[0]
        plen = plen_be if (0 < plen_be < 4096 and not (0 < plen_le < 4096)) else plen_le
        print(f"Len={plen} (raw={binascii.hexlify(len_bytes).decode()})")
        payload = bytearray()
        while len(payload) < plen:
            chunk = ser.read(plen - len(payload))
            if not chunk:
                raise RuntimeError(f"Timeout reading payload ({len(payload)}/{plen})")
            payload.extend(chunk)
        parse_packet(bytes(payload))


def send(url, baud, timeout, text):
    with open_ser(url, baud, timeout) as ser:
        send_line(ser, text.encode())
        with suppress(Exception):
            while True:
                line = ser.readline()
                if not line:
                    break
                print(line.decode(errors="replace").rstrip())


def main():
    ap = argparse.ArgumentParser(description="PDCW CLI over PyFTDI")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--baud", default=DEFAULT_BAUD, type=int)
    ap.add_argument("--timeout", default=3, type=int)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("get-avg")
    p_set = sub.add_parser("set-avg")
    p_set.add_argument("value", type=int)
    sub.add_parser("get-values")
    p_send = sub.add_parser("send")
    p_send.add_argument("text")
    args = ap.parse_args()
    if args.cmd == "get-avg":
        get_avg(args.url, args.baud, args.timeout)
    elif args.cmd == "set-avg":
        set_avg(args.url, args.baud, args.timeout, args.value)
    elif args.cmd == "get-values":
        get_values(args.url, args.baud, args.timeout)
    elif args.cmd == "send":
        send(args.url, args.baud, args.timeout, args.text)


if __name__ == "__main__":
    main()
