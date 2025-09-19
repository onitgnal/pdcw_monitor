from pyftdi.serialext import serial_for_url
URL='ftdi://ftdi:232:FTA1BSZM/1'
with serial_for_url(URL, baudrate=115200, timeout=1, write_timeout=1) as s:
    s.write(b'!c.a=16\r\n'); s.flush(); print('SET:', s.readline().decode(errors='ignore').strip())
    s.write(b'?c.a\r\n');    s.flush(); print('GET:', s.readline().decode(errors='ignore').strip())