# read_values.py
from pyftdi.serialext import serial_for_url
import struct, time, binascii

URL  = 'ftdi://ftdi:232:FTA1BSZM/1'
BAUD = 115200

CHMAP = {
    **{i: f'ADC{i}' for i in range(0x0, 0xA)},
    0x20:'SHT75_X109_T', 0x21:'SHT75_X109_H',
    0x22:'SHT75_X110_T', 0x23:'SHT75_X110_H',
    0x24:'LPS22HB_AB1_T',0x25:'LPS22HB_AB1_P',
    0x26:'LPS22HB_AB2_T',0x27:'LPS22HB_AB2_P',
    0x28:'AB1_V', 0x29:'AB1_IuA',
    0x2A:'AB2_V', 0x2B:'AB2_IuA',
    0x2C:'AB3_V', 0x2D:'AB3_IuA',
}

with serial_for_url(URL, baudrate=BAUD, timeout=3, write_timeout=3) as ser:
    # clean buffers
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)

    # request binary packet
    ser.write(b'?c.v\r\n'); ser.flush()

    # 1) header: '*' (1 byte)
    start = ser.read(1)
    if start != b'*':
        # If we didn’t get binary, show what we did get
        print('Unexpected start:', repr(start + ser.read(64)))
        raise SystemExit(1)

    # 2) length: uint16 LE (bytes from TriggerNr onward)
    len_bytes = ser.read(2)
    if len(len_bytes) != 2:
        raise RuntimeError('Timeout waiting for length')
    plen = struct.unpack('<H', len_bytes)[0]

    # 3) payload: exactly plen bytes
    payload = bytearray()
    while len(payload) < plen:
        chunk = ser.read(plen - len(payload))
        if not chunk:
            raise RuntimeError(f'Timeout reading payload ({len(payload)}/{plen})')
        payload.extend(chunk)

    # Optional: there may be a trailing CRLF; read if present (non-fatal)
    trailer = ser.read(2)

    # ---- decode ----
    off = 0
    trig  = struct.unpack_from('<I', payload, off)[0]; off += 4
    gpio  = struct.unpack_from('<H', payload, off)[0]; off += 2
    nch   = struct.unpack_from('<B', payload, off)[0]; off += 1

    print(f'Len={plen} | Trigger={trig} | GPIO=0x{gpio:04X} | Channels={nch}')

    for i in range(nch):
        ch     = payload[off];        off += 1
        status = payload[off];        off += 1
        val    = struct.unpack_from('<f', payload, off)[0]; off += 4
        name   = CHMAP.get(ch, f'CH_{ch:02X}')
        print(f'{i:02d}: {name:14s} (0x{ch:02X}) status=0x{status:02X} value={val}')

    if trailer:
        print('Trailer (hex):', binascii.hexlify(trailer).decode())