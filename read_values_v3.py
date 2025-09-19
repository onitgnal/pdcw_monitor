# read_values_v3.py
from pyftdi.serialext import serial_for_url
import struct, time, binascii

URL  = 'ftdi://ftdi:232:FTA1BSZM/1'
BAUD = 115200

CHMAP = {
    **{i: f'ADC{i}' for i in range(0x0, 0xA)},   # ADC0..ADC9
    0x0A:'CH_0A', 0x0B:'CH_0B', 0x0C:'CH_0C',    # extra channels seen in your packet
    0x0D:'CH_0D', 0x0E:'CH_0E',
    0x20:'SHT75_X109_T', 0x21:'SHT75_X109_H',
    0x22:'SHT75_X110_T', 0x23:'SHT75_X110_H',
    0x24:'LPS22HB_AB1_T',0x25:'LPS22HB_AB1_P',
    0x26:'LPS22HB_AB2_T',0x27:'LPS22HB_AB2_P',
    0x28:'AB1_V', 0x29:'AB1_IuA',
    0x2A:'AB2_V', 0x2B:'AB2_IuA',
    0x2C:'AB3_V', 0x2D:'AB3_IuA',
}

def read_exact(ser, n, timeout_err):
    buf = bytearray()
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if not chunk:
            raise RuntimeError(f'{timeout_err} ({len(buf)}/{n})')
        buf.extend(chunk)
    return bytes(buf)

with serial_for_url(URL, baudrate=BAUD, timeout=5, write_timeout=3) as ser:
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)

    # request binary packet
    ser.write(b'?c.v\r\n'); ser.flush()

    # header byte
    start = read_exact(ser, 1, 'Timeout waiting for start')
    if start != b'*':
        print('Unexpected start:', repr(start + ser.read(64)))
        raise SystemExit(1)

    # 2-byte length
    len_bytes = read_exact(ser, 2, 'Timeout waiting for length')
    plen_le = struct.unpack('<H', len_bytes)[0]
    plen_be = struct.unpack('>H', len_bytes)[0]
    # choose sane length
    if 0 < plen_be < 4096 and not (0 < plen_le < 4096):
        plen, endian = plen_be, 'BE'
    else:
        plen, endian = plen_le, 'LE'
    print(f'LenBytes={binascii.hexlify(len_bytes).decode()} -> plen={plen} ({endian})')

    payload = read_exact(ser, plen, 'Timeout reading payload')
    trailer = ser.read(2)  # optional CRLF

    # decode header (still little-endian for these fields unless spec says otherwise)
    off = 0
    trig  = struct.unpack_from('<I', payload, off)[0]; off += 4
    gpio  = struct.unpack_from('<H', payload, off)[0]; off += 2
    nch   = struct.unpack_from('<B', payload, off)[0]; off += 1
    print(f'Header: Trigger={trig} GPIO=0x{gpio:04X} Channels={nch}')

    # channel loop: numbers & status are bytes; values appear to be BIG-ENDIAN floats
    for i in range(nch):
        ch     = payload[off]; off += 1
        status = payload[off]; off += 1
        val    = struct.unpack_from('>f', payload, off)[0]; off += 4   # <-- big-endian float
        name   = CHMAP.get(ch, f'CH_{ch:02X}')
        # neat formatting for typical quantities
        if name.endswith('_T'):
            pv = f'{val:.2f} °C'
        elif name.endswith('_H'):
            pv = f'{val:.2f} %RH'
        elif name.endswith('_P'):
            pv = f'{val:.2f} hPa'
        elif name.endswith('_V'):
            pv = f'{val:.4f} V'
        elif name.endswith('_IuA'):
            pv = f'{val:.2f} µA'
        else:
            pv = f'{val:.6g}'
        print(f'{i:02d}: {name:14s} (0x{ch:02X}) status=0x{status:02X} value={pv}')

    if trailer:
        print('Trailer (hex):', binascii.hexlify(trailer).decode())