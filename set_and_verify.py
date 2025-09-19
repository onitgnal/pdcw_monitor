from pyftdi.serialext import serial_for_url
import time

URL  = 'ftdi://ftdi:232:FTA1BSZM/1'
BAUD = 115200

ser = serial_for_url(URL, baudrate=BAUD, timeout=2)
try:
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.05)

    # set averaging to 512 (device may round if needed)
    ser.write(b'!c.a=512\r\n'); ser.flush()
    resp1 = ser.readline()
    print('SET resp:', repr(resp1))

    # read back
    ser.write(b'?c.a\r\n'); ser.flush()
    resp2 = ser.readline()
    print('GET resp:', repr(resp2))

finally:
    ser.close()