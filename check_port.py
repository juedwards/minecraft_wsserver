import psutil
import sys

def check_port_usage(port):
    """Check what process is using a specific port"""
    for conn in psutil.net_connections():
        if conn.laddr.port == port:
            try:
                process = psutil.Process(conn.pid)
                print(f"Port {port} is being used by:")
                print(f"  PID: {conn.pid}")
                print(f"  Process: {process.name()}")
                print(f"  Command: {' '.join(process.cmdline())}")
                return conn.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                print(f"Port {port} is in use by PID {conn.pid} (access denied)")
                return conn.pid
    print(f"Port {port} is not in use")
    return None

if __name__ == "__main__":
    pid = check_port_usage(3000)
    if pid:
        response = input("\nDo you want to kill this process? (y/n): ")
        if response.lower() == 'y':
            try:
                process = psutil.Process(pid)
                process.terminate()
                print(f"Process {pid} terminated")
            except Exception as e:
                print(f"Error terminating process: {e}")