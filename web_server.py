import os
import subprocess
import threading
import json
from flask import Flask, render_template, jsonify, send_file, send_from_directory
from datetime import datetime
import signal
import sys
import time
from pathlib import Path
import socket
import psutil  # Add this to requirements.txt

# ========================================================================
# WEB FRONTEND FOR MINECRAFT DATA CAPTURE SERVER
# ========================================================================
# This web server provides:
# 1. Start/Stop control for the Minecraft capture server
# 2. Live status monitoring
# 3. File browser for /data/ folder
# 4. Download functionality for captured data
# ========================================================================

app = Flask(__name__)

class ServerManager:
    """
    Manages the Minecraft data capture server process
    """
    def __init__(self):
        self.process = None
        self.is_running = False
        self.start_time = None
        self.output_lines = []
        self.max_output_lines = 100
        self.server_ip = self.get_server_ip()
        
        # Ensure data folder exists
        self.data_folder = "data"  # Use relative path for easier access
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
        
        # Check for zombie processes on startup
        self.cleanup_zombie_processes()
    
    def cleanup_zombie_processes(self):
        """Clean up any lingering Python processes running the capture server"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # Check if it's a Python process running our capture server
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline and any('minecraft_data_capture_server.py' in arg for arg in cmdline):
                            print(f"Found zombie capture server process (PID: {proc.info['pid']}), terminating...")
                            proc.terminate()
                            time.sleep(1)  # Give it time to terminate
                            if proc.is_running():
                                proc.kill()  # Force kill if still running
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def get_server_ip(self):
        """Get the external IP address of the server"""
        try:
            # Create a socket connection to determine the local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Connect to a public DNS server (doesn't actually send data)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            # Fallback to localhost if we can't determine IP
            return "localhost"
    
    def check_process_alive(self):
        """Check if the process is actually running"""
        if self.process:
            poll = self.process.poll()
            if poll is not None:
                # Process has terminated
                self.is_running = False
                self.process = None
                return False
            return True
        return False
    
    def start_server(self):
        """Start the Minecraft capture server"""
        # First check if process is actually alive
        if self.check_process_alive():
            return False, "Server is already running"
        
        # Reset state if process is dead
        self.is_running = False
        self.process = None
        
        # Clean up any zombie processes
        self.cleanup_zombie_processes()
        
        try:
            # Start the capture server as a subprocess
            self.process = subprocess.Popen(
                [sys.executable, 'minecraft_data_capture_server.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Wait a moment to ensure it started
            time.sleep(0.5)
            
            # Check if process started successfully
            if self.process.poll() is not None:
                # Process died immediately
                return False, "Server failed to start - check if minecraft_data_capture_server.py exists"
            
            self.is_running = True
            self.start_time = datetime.now()
            self.output_lines = ["Server starting..."]
            
            # Start thread to capture output
            output_thread = threading.Thread(target=self._capture_output)
            output_thread.daemon = True
            output_thread.start()
            
            return True, "Server started successfully"
        except FileNotFoundError:
            return False, "minecraft_data_capture_server.py not found in current directory"
        except Exception as e:
            return False, f"Failed to start server: {str(e)}"
    
    def stop_server(self):
        """Stop the Minecraft capture server"""
        if not self.check_process_alive():
            self.is_running = False
            self.process = None
            return True, "Server was not running"
        
        try:
            if self.process:
                # Send termination signal
                self.process.terminate()
                # Wait for process to end
                self.process.wait(timeout=5)
                
            self.is_running = False
            self.process = None
            self.output_lines.append("Server stopped")
            return True, "Server stopped successfully"
        except subprocess.TimeoutExpired:
            # Force kill if it doesn't stop gracefully
            if self.process:
                self.process.kill()
            self.is_running = False
            self.process = None
            return True, "Server force stopped"
        except Exception as e:
            self.is_running = False
            self.process = None
            return False, f"Error stopping server: {str(e)}"
    
    def _capture_output(self):
        """Capture output from the subprocess"""
        if self.process:
            try:
                for line in iter(self.process.stdout.readline, ''):
                    if line:
                        self.output_lines.append(line.strip())
                        # Keep only recent lines
                        if len(self.output_lines) > self.max_output_lines:
                            self.output_lines.pop(0)
                    
                    # Check if process is still alive
                    if self.process.poll() is not None:
                        self.is_running = False
                        self.output_lines.append("Server process terminated")
                        break
            except Exception as e:
                self.output_lines.append(f"Error reading output: {str(e)}")
    
    def get_status(self):
        """Get current server status"""
        # Update running status based on actual process state
        self.check_process_alive()
        
        status = {
            'is_running': self.is_running,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'uptime': str(datetime.now() - self.start_time) if self.start_time and self.is_running else None,
            'output': self.output_lines[-20:],  # Last 20 lines
            'server_ip': self.server_ip,  # Include server IP in status
            'minecraft_port': 3000
        }
        return status
    
    def get_data_files(self):
        """Get list of data files in the data folder"""
        files = []
        try:
            for file in os.listdir(self.data_folder):
                if file.endswith('.json'):
                    file_path = os.path.join(self.data_folder, file)
                    stat = os.stat(file_path)
                    files.append({
                        'name': file,
                        'size': self._format_size(stat.st_size),
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        'size_bytes': stat.st_size
                    })
            # Sort by modified date (newest first)
            files.sort(key=lambda x: x['modified'], reverse=True)
        except Exception as e:
            print(f"Error listing files: {e}")
        return files
    
    def _format_size(self, size_bytes):
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

# Create server manager instance
server_manager = ServerManager()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_server():
    """API endpoint to start the server"""
    success, message = server_manager.start_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop', methods=['POST'])
def stop_server():
    """API endpoint to stop the server"""
    success, message = server_manager.stop_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/restart', methods=['POST'])
def restart_server():
    """API endpoint to restart the server"""
    # First stop
    server_manager.stop_server()
    time.sleep(1)  # Brief pause
    # Then start
    success, message = server_manager.start_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/status')
def get_status():
    """API endpoint to get server status"""
    return jsonify(server_manager.get_status())

@app.route('/api/files')
def get_files():
    """API endpoint to get list of data files"""
    return jsonify({'files': server_manager.get_data_files()})

@app.route('/download/<filename>')
def download_file(filename):
    """Download a specific data file"""
    try:
        return send_from_directory(server_manager.data_folder, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/file-preview/<filename>')
def preview_file(filename):
    """Get a preview of file contents"""
    try:
        file_path = os.path.join(server_manager.data_folder, filename)
        with open(file_path, 'r') as f:
            data = json.load(f)
            # Return summary info
            preview = {
                'filename': filename,
                'server_start_time': data.get('server_start_time'),
                'total_events': len(data.get('events', [])),
                'total_players': len(data.get('players', {})),
                'players': list(data.get('players', {}).keys())
            }
            return jsonify(preview)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Signal handler for graceful shutdown
def signal_handler(sig, frame):
    print('\nShutting down web server...')
    if server_manager.is_running:
        server_manager.stop_server()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    # Ensure the minecraft capture script exists
    if not os.path.exists('minecraft_data_capture_server.py'):
        print("Error: minecraft_data_capture_server.py not found!")
        print("Please ensure the Minecraft capture server script is in the same directory.")
        sys.exit(1)
    
    print("=" * 60)
    print("Minecraft Data Capture Web Interface")
    print("=" * 60)
    print(f"Server IP: {server_manager.server_ip}")
    print(f"Starting web server on http://{server_manager.server_ip}:5000")
    print("Open this URL in your browser to access the interface")
    print("Press Ctrl+C to stop the web server")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)