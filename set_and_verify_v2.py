# set_and_verify_v2.py
from pyftdi.serialext import serial_for_url
import time, binascii

URL  = 'ftdi://ftdi:232:FTA1BSZM/1'
BAUD = 115200

with serial_for_url(URL, baudrate=BAUD, timeout=3, write_timeout=3) as ser:
    # clean buffers
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)

    # write: set averaging to 512
    ser.write(b'!c.a=512\r\n'); ser.flush()
    time.sleep(0.05)
    resp1 = ser.readline()
    print('SET resp:', repr(resp1))

    # read-back with a small delay + fallback
    ser.reset_input_buffer()  # start fresh
    ser.write(b'?c.a\r\n'); ser.flush()
    time.sleep(0.10)

    line = ser.readline()
    if line:
        print('GET resp (line):', repr(line))
    else:
        # fallback: check any pending bytes and dump raw
        time.sleep(0.25)
        try:
            pending = ser.in_waiting
        except Exception:
            pending = 0
        print('GET resp: no line yet, in_waiting =', pending)
        if pending:
            data = ser.read(pending)
            print('GET resp (raw hex):', binascii.hexlify(data))
        else:
            print('GET resp: <timeout>')