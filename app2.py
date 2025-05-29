import os
import subprocess
import threading
import json
from flask import Flask, render_template, jsonify, send_file, send_from_directory, request
from datetime import datetime
import signal
import sys
import time
from pathlib import Path
import socket
import psutil
import shutil
import requests

app = Flask(__name__)

class ServerManager:
    def __init__(self):
        self.process = None
        self.is_running = False
        self.start_time = None
        self.output_lines = []
        self.max_output_lines = 100
        self.server_ip = self.get_server_ip()
        self.external_ip = self.get_external_ip()
        
        self.server_script = "minecraft_data_capture_server_with_commands.py"
        
        self.data_folder = "data"
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
        
        self.command_file = os.path.join(self.data_folder, "pending_commands.json")
        
        # Check script exists
        if not os.path.exists(self.server_script):
            print(f"Warning: {self.server_script} not found!")
            for script in ["minecraft_data_capture_server.py", "minecraft_data_capture_server_simple.py"]:
                if os.path.exists(script):
                    self.server_script = script
                    print(f"Using {self.server_script} instead")
                    break
        
        self.cleanup_zombie_processes()
        
        # Command presets
        self.command_presets = {
            "time_day": "time set day",
            "time_night": "time set night",
            "time_noon": "time set noon",
            "weather_clear": "weather clear",
            "weather_rain": "weather rain",
            "weather_thunder": "weather thunder",
            "gamemode_creative": "gamemode creative @a",
            "gamemode_survival": "gamemode survival @a",
            "gamemode_adventure": "gamemode adventure @a",
            "give_diamond": "give @a diamond 64",
            "give_iron": "give @a iron_ingot 64",
            "give_wood": "give @a oak_log 64",
            "give_food": "give @a cooked_beef 64",
            "give_tools": "give @a diamond_pickaxe 1",
            "effect_speed": "effect @a speed 600 2",
            "effect_jump": "effect @a jump_boost 600 2",
            "effect_night_vision": "effect @a night_vision 600",
            "effect_clear": "effect @a clear",
            "summon_pig": "summon pig ~ ~ ~",
            "summon_cow": "summon cow ~ ~ ~",
            "summon_chicken": "summon chicken ~ ~ ~",
            "kill_all_mobs": "kill @e[type=!player]",
            "tp_all_to_spawn": "tp @a 0 100 0",
            "clear_inventory": "clear @a",
            "say_hello": 'tellraw @a {"rawtext":[{"text":"§e§lHello from Web Interface!"}]}',
            "give_building_blocks": "give @a stone 64",
            "set_world_spawn": "setworldspawn ~ ~ ~",
            "enable_coordinates": "gamerule showcoordinates true",
            "disable_coordinates": "gamerule showcoordinates false",
            "keep_inventory_on": "gamerule keepinventory true",
            "keep_inventory_off": "gamerule keepinventory false",
            "always_day": "gamerule dodaylightcycle false",
            "normal_day_cycle": "gamerule dodaylightcycle true"
        }
    
    def cleanup_zombie_processes(self):
        """Clean up any lingering Python processes"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and 'python' in proc.info['name'].lower():
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline and any('minecraft_data_capture_server' in arg for arg in cmdline):
                            print(f"Found zombie process (PID: {proc.info['pid']}), terminating...")
                            proc.terminate()
                            time.sleep(1)
                            if proc.is_running():
                                proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def get_server_ip(self):
        """Get the local IP address"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"
    
    def get_external_ip(self):
        """Get the external/public IP address"""
        try:
            # Try multiple services in case one is down
            services = [
                'https://api.ipify.org?format=json',
                'https://ipapi.co/json/',
                'https://ifconfig.me/all.json',
                'https://ipinfo.io/json'
            ]
            
            for service in services:
                try:
                    response = requests.get(service, timeout=5)
                    data = response.json()
                    # Different services return IP in different fields
                    ip = data.get('ip') or data.get('ip_addr') or data.get('origin')
                    if ip:
                        print(f"External IP detected: {ip}")
                        return ip
                except:
                    continue
            
            # If all services fail, fall back to local IP
            print("Could not determine external IP, using local IP")
            return self.server_ip
            
        except Exception as e:
            print(f"Error getting external IP: {e}")
            return self.server_ip
    
    def send_minecraft_command(self, command):
        """Add command to the pending commands file"""
        if not self.is_running:
            return False, "Server is not running"
        
        try:
            # Read existing commands
            commands = []
            if os.path.exists(self.command_file):
                try:
                    with open(self.command_file, 'r') as f:
                        commands = json.load(f)
                except:
                    commands = []
            
            # Add new command
            commands.append(command)
            
            # Write back
            with open(self.command_file, 'w') as f:
                json.dump(commands, f)
            
            return True, f"Command queued: {command}"
        except Exception as e:
            return False, f"Error sending command: {str(e)}"
    
    def check_process_alive(self):
        """Check if the process is actually running"""
        if self.process:
            poll = self.process.poll()
            if poll is not None:
                self.is_running = False
                self.process = None
                return False
            return True
        return False
    
    def start_server(self):
        """Start the Minecraft capture server"""
        if self.check_process_alive():
            return False, "Server is already running"
        
        self.is_running = False
        self.process = None
        
        self.cleanup_zombie_processes()
        
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            
            self.process = subprocess.Popen(
                [sys.executable, '-u', self.server_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                creationflags=creationflags
            )
            
            time.sleep(1)
            
            if self.process.poll() is not None:
                output = ""
                if self.process.stdout:
                    output = self.process.stdout.read()
                return False, f"Server failed to start. Output: {output}"
            
            self.is_running = True
            self.start_time = datetime.now()
            self.output_lines = ["Server starting..."]
            
            # Start output capture thread
            output_thread = threading.Thread(target=self._capture_output)
            output_thread.daemon = True
            output_thread.start()
            
            return True, "Server started successfully"
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
                self.process.terminate()
                self.process.wait(timeout=5)
                
            self.is_running = False
            self.process = None
            self.output_lines.append("Server stopped")
            return True, "Server stopped successfully"
        except subprocess.TimeoutExpired:
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
        if self.process and self.process.stdout:
            try:
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        break
                    
                    line = line.strip()
                    if line:
                        self.output_lines.append(line)
                        if len(self.output_lines) > self.max_output_lines:
                            self.output_lines.pop(0)
                    
                    if self.process.poll() is not None:
                        self.is_running = False
                        self.output_lines.append("Server process terminated")
                        break
            except Exception as e:
                self.output_lines.append(f"Error reading output: {str(e)}")
    
    def get_status(self):
        """Get current server status"""
        self.check_process_alive()
        
        # Check if commands are being processed
        commands_pending = 0
        if os.path.exists(self.command_file):
            try:
                with open(self.command_file, 'r') as f:
                    commands = json.load(f)
                    commands_pending = len(commands)
            except:
                pass
        
        # Use external IP if available, otherwise local
        display_ip = self.external_ip if self.external_ip else self.server_ip
        
        status = {
            'is_running': self.is_running,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'uptime': str(datetime.now() - self.start_time) if self.start_time and self.is_running else None,
            'output': self.output_lines[-20:],
            'server_ip': display_ip,  # Use the external IP for display
            'local_ip': self.server_ip,  # Keep local IP for reference
            'external_ip': self.external_ip,  # Include external IP
            'minecraft_port': 19131,
            'commands_pending': commands_pending,
            'command_presets': self.command_presets
        }
        return status
    
    def get_data_files(self):
        """Get list of data files"""
        files = []
        try:
            for file in os.listdir(self.data_folder):
                if file.endswith('.json') or file.endswith('.log'):
                    if file == "pending_commands.json":
                        continue
                    file_path = os.path.join(self.data_folder, file)
                    stat = os.stat(file_path)
                    files.append({
                        'name': file,
                        'size': self._format_size(stat.st_size),
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                        'size_bytes': stat.st_size,
                        'type': 'log' if file.endswith('.log') else 'data'
                    })
            files.sort(key=lambda x: x['modified'], reverse=True)
        except Exception as e:
            print(f"Error listing files: {e}")
        return files
    
    def clear_all_logs(self):
        """Clear all log and data files"""
        if self.is_running:
            return False, "Cannot clear logs while server is running. Please stop the server first."
        
        try:
            deleted_count = 0
            deleted_size = 0
            
            for file in os.listdir(self.data_folder):
                if file.endswith('.json') or file.endswith('.log'):
                    if file == "pending_commands.json":
                        continue
                    file_path = os.path.join(self.data_folder, file)
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_count += 1
                    deleted_size += file_size
            
            self.output_lines = []
            
            return True, f"Cleared {deleted_count} files ({self._format_size(deleted_size)})"
        except Exception as e:
            return False, f"Error clearing logs: {str(e)}"
    
    def _format_size(self, size_bytes):
        """Format file size"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

# Create server manager instance
server_manager = ServerManager()

@app.route('/')
def index():
    return render_template('index2.html')

@app.route('/api/start', methods=['POST'])
def start_server():
    success, message = server_manager.start_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/stop', methods=['POST'])
def stop_server():
    success, message = server_manager.stop_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/restart', methods=['POST'])
def restart_server():
    server_manager.stop_server()
    time.sleep(1)
    success, message = server_manager.start_server()
    return jsonify({'success': success, 'message': message})

@app.route('/api/status')
def get_status():
    return jsonify(server_manager.get_status())

@app.route('/api/files')
def get_files():
    return jsonify({'files': server_manager.get_data_files()})

@app.route('/api/clear-logs', methods=['POST'])
def clear_logs():
    success, message = server_manager.clear_all_logs()
    return jsonify({'success': success, 'message': message})

@app.route('/api/send-command', methods=['POST'])
def send_command():
    """Queue a command for the Minecraft server"""
    data = request.json
    command = data.get('command', '')
    
    if not command:
        return jsonify({'success': False, 'message': 'No command provided'})
    
    success, message = server_manager.send_minecraft_command(command)
    return jsonify({'success': success, 'message': message})

@app.route('/download/<filename>')
def download_file(filename):
    try:
        return send_from_directory(server_manager.data_folder, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404

@app.route('/api/file-preview/<filename>')
def preview_file(filename):
    try:
        file_path = os.path.join(server_manager.data_folder, filename)
        
        if filename.endswith('.log'):
            with open(file_path, 'r') as f:
                lines = f.readlines()
                preview = {
                    'filename': filename,
                    'type': 'log',
                    'total_lines': len(lines),
                    'preview_lines': lines[-50:] if len(lines) > 50 else lines
                }
                return jsonify(preview)
        
        with open(file_path, 'r') as f:
            data = json.load(f)
            preview = {
                'filename': filename,
                'type': 'data',
                'server_start_time': data.get('server_start'),
                'total_events': len(data.get('events', [])),
                'total_players': len(data.get('players', {})),
                'players': list(data.get('players', {}).keys()),
                'stats': data.get('stats', {})
            }
            return jsonify(preview)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze/<filename>')
def analyze_file(filename):
    try:
        file_path = os.path.join(server_manager.data_folder, filename)
        if not filename.endswith('.json'):
            return "Analysis only available for JSON files.", 400
        with open(file_path, 'r') as f:
            data = json.load(f)
        # Example analysis: count events, players, stats, etc.
        analysis = {
            'filename': filename,
            'server_start_time': data.get('server_start'),
            'total_events': len(data.get('events', [])),
            'total_players': len(data.get('players', {})),
            'players': list(data.get('players', {}).keys()),
            'stats': data.get('stats', {}),
            # Add more analysis as needed
        }
        return render_template('analyze.html', analysis=analysis)
    except Exception as e:
        return f"Error analyzing file: {str(e)}", 500

def signal_handler(sig, frame):
    print('\nShutting down web server...')
    if server_manager.is_running:
        server_manager.stop_server()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
    print("=" * 60)
    print("Minecraft Data Capture Web Interface - Enhanced")
    print("=" * 60)
    print(f"Local IP: {server_manager.server_ip}")
    print(f"External IP: {server_manager.external_ip}")
    print(f"Starting web server on http://0.0.0.0:5000")
    print("Open this URL in your browser to access the interface")
    print("Press Ctrl+C to stop the web server")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)