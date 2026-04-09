import serial
import time

PORT = 'COM3'
BAUD = 115200

def send_gcode(ser, line):
    line = line.strip()
    if not line or line.startswith(';'):
        return None  # skip empty lines and comments
    
    print(f'>> {line}')
    ser.write((line + '\n').encode())
    
    # Wait for response
    response = ser.readline().decode().strip()
    print(f'<< {response}')
    return response

def wait_for_idle(ser, poll_interval=0.5):
    """Poll status until machine is Idle."""
    while True:
        ser.write(b'?')
        status = ser.readline().decode().strip()
        print(f'   status: {status}')
        if 'Idle' in status:
            break
        time.sleep(poll_interval)

def run_file(ser, filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    for line in lines:
        response = send_gcode(ser, line)
        if response and 'error' in response.lower():
            print(f'[ERROR] Halting. grbl said: {response}')
            break

def main():
    with serial.Serial(PORT, BAUD, timeout=5) as ser:
        time.sleep(2)  # Wait for grbl to initialize
        ser.flushInput()
        
        # grblHAL sends a startup message — read and print it
        startup = ser.read(ser.in_waiting).decode(errors='ignore')
        print(f'Startup: {startup}')
        
        # Send a file
        run_file(ser, 'my_program.gcode')
        
        # Wait until motion is done before closing
        wait_for_idle(ser)
        print('Done.')

if __name__ == '__main__':
    main()