# probe_serial.py
from pyftdi.serialext import serial_for_url
import time

URL = 'ftdi://ftdi:232:FTA1BSZM/1'  # from your discovery
BAUD = 115200                       # first try; we can change if needed

ser = serial_for_url(URL, baudrate=BAUD, timeout=2)
try:
    # clean any pending bytes
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)

    # Send read-only query for averaging factor
    cmd = b'?c.a\r\n'
    ser.write(cmd)
    ser.flush()

    # Read one line terminated by CRLF
    line = ser.readline()  # expects something like b'+512\r\n' or b'-ERR=...\r\n'
    print(f'BAUD={BAUD} response (repr):', repr(line))

finally:
    ser.close()