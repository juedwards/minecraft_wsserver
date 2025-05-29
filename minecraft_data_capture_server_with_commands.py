import asyncio
import websockets
import json
import uuid
import sys
import socket
from pathlib import Path
from datetime import datetime
import threading
import queue

# Force output to be unbuffered
import os
os.environ['PYTHONUNBUFFERED'] = '1'

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    # Set console to UTF-8
    os.system("chcp 65001 > nul")

print("Minecraft Data Capture Server Starting...", flush=True)

# Setup data directories
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Create timestamped files
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
DATA_FILE = DATA_DIR / f"MinecraftData_{timestamp}.json"
LOG_FILE = DATA_DIR / f"server_{timestamp}.log"
COMMAND_FILE = DATA_DIR / "pending_commands.json"
STRUCTURES_FILE = Path("structures.json")

# Main data structure
minecraft_data = {
    "server_start": datetime.now().isoformat(),
    "events": [],
    "players": {},
    "stats": {
        "total_events": 0,
        "messages": 0,
        "blocks_placed": 0,
        "blocks_broken": 0,
        "commands_sent": 0,
        "commands_successful": 0,
        "structures_built": 0
    }
}

# Events to subscribe to
MINECRAFT_EVENTS = [
    "PlayerJoin", "PlayerLeave", "PlayerMessage", "PlayerTransform", 
    "BlockPlaced", "BlockBroken", "ItemUsed", "ItemCrafted",
    "PlayerTeleported", "MobKilled", "PlayerDied", "CommandExecuted",
    "PlayerTravelled"
]

# Global command queue
command_queue = queue.Queue()

# Track player positions
player_positions = {}

# Load structures from file
STRUCTURES = {}
try:
    if STRUCTURES_FILE.exists():
        with open(STRUCTURES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            STRUCTURES = data.get('structures', {})
            print(f"Loaded {len(STRUCTURES)} structures from {STRUCTURES_FILE}")
    else:
        print(f"Warning: {STRUCTURES_FILE} not found. !build command will not work.")
except Exception as e:
    print(f"Error loading structures: {e}")

def log_message(message):
    """Log message to both console and file"""
    # Replace emojis with ASCII for console compatibility
    console_message = message
    if sys.platform == "win32":
        replacements = {
            '📤': '[OUT]',
            '❌': '[X]',
            '✅': '[OK]',
            '💬': '[CHAT]',
            '🔨': '[PLACED]',
            '⛏️': '[BROKEN]',
            '📌': '[EVENT]',
            '💾': '[SAVED]',
            '🛑': '[STOP]',
            '📊': '[STATS]',
            '🏗️': '[BUILD]'
        }
        for emoji, text in replacements.items():
            console_message = console_message.replace(emoji, text)
    
    print(console_message, flush=True)
    
    # Keep emojis in log file
    with open(LOG_FILE, "a", encoding='utf-8') as f:
        f.write(f"{datetime.now().isoformat()} - {message}\n")

def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "localhost"

def save_data():
    """Save the minecraft data to JSON file."""
    try:
        with DATA_FILE.open("w", encoding='utf-8') as f:
            json.dump(minecraft_data, f, indent=2)
        return True
    except Exception as e:
        log_message(f"Error saving data: {e}")
        return False

def check_pending_commands():
    """Check for pending commands from the web interface"""
    try:
        if COMMAND_FILE.exists():
            with open(COMMAND_FILE, 'r', encoding='utf-8') as f:
                commands = json.load(f)
            
            # Add commands to queue
            for cmd in commands:
                command_queue.put(cmd)
            
            # Clear the file
            with open(COMMAND_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f)
            
            return len(commands)
    except Exception as e:
        log_message(f"Error checking pending commands: {e}")
    return 0

async def send_command(websocket, command_text):
    """Send a command to Minecraft."""
    request_id = str(uuid.uuid4())
    
    # Build the command message
    message = {
        "header": {
            "version": 1,
            "requestId": request_id,
            "messagePurpose": "commandRequest",
            "messageType": "commandRequest"
        },
        "body": {
            "version": 1,
            "commandLine": command_text,
            "origin": {
                "type": "player"
            }
        }
    }
    
    try:
        await websocket.send(json.dumps(message))
        minecraft_data["stats"]["commands_sent"] += 1
        log_message(f"📤 Sent command: {command_text}")
        return True
    except Exception as e:
        log_message(f"❌ Error sending command: {e}")
        return False

async def subscribe_event(websocket, event_name):
    """Subscribe to a specific Minecraft event."""
    await websocket.send(json.dumps({
        "header": {
            "version": 1,
            "requestId": str(uuid.uuid4()),
            "messagePurpose": "subscribe",
            "messageType": "commandRequest"
        },
        "body": {
            "eventName": event_name
        }
    }))

def extract_player_name(body):
    """Extract player name from various possible locations in the event body."""
    player_data = body.get("player")
    
    if isinstance(player_data, dict):
        player_name = player_data.get("name") or player_data.get("PlayerName")
    else:
        player_name = player_data
    
    if not player_name:
        player_name = body.get("sender")
    if not player_name:
        properties = body.get("properties", {})
        if isinstance(properties, dict):
            player_name = properties.get("PlayerName")
    
    if player_name:
        player_name = str(player_name)
    
    return player_name

def extract_position(data, pos_key="position"):
    """Extract position information from data."""
    pos = data.get(pos_key, {})
    
    if isinstance(pos, dict):
        x = pos.get("x")
        y = pos.get("y") 
        z = pos.get("z")
        
        try:
            x = round(float(x), 2) if x is not None else None
            y = round(float(y), 2) if y is not None else None
            z = round(float(z), 2) if z is not None else None
        except:
            pass
            
        return x, y, z
    elif isinstance(pos, list) and len(pos) >= 3:
        return pos[0], pos[1], pos[2]
    
    return None, None, None

def extract_block_info(body):
    """Extract block information from event body."""
    block_data = body.get("block")
    
    if isinstance(block_data, dict):
        block_name = (
            block_data.get("id") or 
            block_data.get("name") or 
            block_data.get("type")
        )
    elif isinstance(block_data, str):
        block_name = block_data
    else:
        block_name = body.get("blockType") or body.get("blockName") or "unknown_block"
    
    # Get player position
    player_x, player_y, player_z = None, None, None
    player_data = body.get("player", {})
    if isinstance(player_data, dict):
        player_x, player_y, player_z = extract_position(player_data, "position")
    
    return block_name, player_x, player_y, player_z

async def build_structure(websocket, structure_name, player_name, base_x, base_y, base_z):
    """Build a structure at the specified location."""
    if structure_name not in STRUCTURES:
        available = ", ".join(STRUCTURES.keys())
        await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cUnknown structure: {structure_name}\\n§7Available: {available}"}}]}}')
        return False
    
    structure = STRUCTURES[structure_name]
    blocks = structure.get("blocks", [])
    
    await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§eBuilding {structure.get("name", structure_name)}..."}}]}}')
    
    # Place blocks
    blocks_placed = 0
    for block_data in blocks:
        dx = block_data.get("dx", 0)
        dy = block_data.get("dy", 0)
        dz = block_data.get("dz", 0)
        block_type = block_data.get("block", "stone")
        
        # Handle block states/data
        if "data" in block_data and isinstance(block_data["data"], dict):
            # For Bedrock Edition, we need to handle block states differently
            # For now, just use the base block type
            # TODO: Convert Java block states to Bedrock format
            pass
        
        x = int(base_x + dx)
        y = int(base_y + dy)
        z = int(base_z + dz)
        
        await send_command(websocket, f"setblock {x} {y} {z} {block_type}")
        blocks_placed += 1
        
        # Small delay to prevent overwhelming the server
        if blocks_placed % 10 == 0:
            await asyncio.sleep(0.1)
    
    minecraft_data["stats"]["structures_built"] += 1
    await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§aBuilt {structure.get("name", structure_name)} ({blocks_placed} blocks)"}}]}}')
    log_message(f"Built {structure_name} for {player_name} at ({base_x}, {base_y}, {base_z})")
    return True

async def process_chat_command(websocket, player_name, message):
    """Process chat commands starting with !"""
    parts = message.split()
    command = parts[0].lower()
    
    if command == "!help":
        help_text = "§eCommands:\\n"
        help_text += "§7!help - Show this help\\n"
        help_text += "§7!stats - Show your statistics\\n"
        help_text += "§7!time <day/night/noon> - Change time\\n"
        help_text += "§7!weather <clear/rain/thunder> - Change weather\\n"
        help_text += "§7!gamemode <mode> - Change game mode\\n"
        help_text += "§7!build <structure> - Build a structure\\n"
        help_text += "§7!structures - List available structures"
        await send_command(websocket, f'tellraw @a {{"rawtext":[{{"text":"{help_text}"}}]}}')
    
    elif command == "!stats":
        if player_name in minecraft_data["players"]:
            stats = minecraft_data["players"][player_name]
            stats_text = f"§b{player_name}'s Stats:\\n"
            stats_text += f"§7Blocks placed: {stats.get('blocks_placed', 0)}\\n"
            stats_text += f"§7Blocks broken: {stats.get('blocks_broken', 0)}\\n"
            stats_text += f"§7Messages sent: {stats.get('messages', 0)}"
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"{stats_text}"}}]}}')
    
    elif command == "!time":
        if len(parts) > 1:
            time_val = parts[1]
            await send_command(websocket, f"time set {time_val}")
        else:
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cUsage: !time day/night/noon"}}]}}')
    
    elif command == "!weather":
        if len(parts) > 1:
            weather = parts[1]
            await send_command(websocket, f"weather {weather}")
        else:
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cUsage: !weather clear/rain/thunder"}}]}}')
    
    elif command == "!gamemode":
        if len(parts) > 1:
            mode = parts[1]
            await send_command(websocket, f"gamemode {mode} {player_name}")
        else:
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cUsage: !gamemode creative/survival/adventure"}}]}}')
    
    elif command == "!structures":
        if STRUCTURES:
            structures_list = "§eAvailable structures:\\n"
            for name, data in STRUCTURES.items():
                structures_list += f"§7{name} - {data.get('description', 'No description')}\\n"
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"{structures_list}"}}]}}')
        else:
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cNo structures loaded!"}}]}}')
    
    elif command == "!build":
        if len(parts) > 1:
            structure_name = parts[1].lower()
            
            # Get player position
            if player_name in player_positions:
                pos = player_positions[player_name]
                x, y, z = pos['x'], pos['y'], pos['z']
                
                # Offset slightly so structure doesn't build on top of player
                await build_structure(websocket, structure_name, player_name, x + 2, y, z + 2)
            else:
                await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cCannot determine your position. Move around first!"}}]}}')
        else:
            available = ", ".join(STRUCTURES.keys()) if STRUCTURES else "none"
            await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§cUsage: !build <structure>\\n§7Available: {available}"}}]}}')

async def handler(websocket):
    """Handle WebSocket connections from Minecraft."""
    client_ip = websocket.remote_address[0]
    log_message(f"[+] Connection from {client_ip}")
    
    # Subscribe to all events
    for event in MINECRAFT_EVENTS:
        await subscribe_event(websocket, event)
    
    log_message(f"[{client_ip}] Subscribed to {len(MINECRAFT_EVENTS)} events")
    
    # Send welcome message
    await send_command(websocket, 'tellraw @a {"rawtext":[{"text":"§e§lWebSocket Server Connected!\\n§7Commands enabled. Type !help for info."}]}')
    
    # Create a task to periodically check for commands
    async def command_checker():
        while True:
            try:
                # Check file for pending commands
                num_commands = check_pending_commands()
                
                # Process commands from queue
                while not command_queue.empty():
                    try:
                        cmd = command_queue.get_nowait()
                        await send_command(websocket, cmd)
                        await asyncio.sleep(0.1)  # Small delay between commands
                    except queue.Empty:
                        break
                
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                log_message(f"Command checker error: {e}")
                break
    
    # Start command checker task
    command_task = asyncio.create_task(command_checker())
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            
            header = data.get("header", {})
            body = data.get("body", {})
            event_name = header.get("eventName", "")
            message_purpose = header.get("messagePurpose", "")
            
            # Handle command responses
            if message_purpose == "commandResponse":
                request_id = header.get("requestId", "")
                status_code = body.get("statusCode", -1)
                status_message = body.get("statusMessage", "Unknown")
                
                if status_code == 0:
                    minecraft_data["stats"]["commands_successful"] += 1
                    # Don't log every successful block placement
                    if "setblock" not in status_message.lower():
                        log_message(f"✅ Command successful: {status_message}")
                else:
                    log_message(f"❌ Command failed (code {status_code}): {status_message}")
                continue
            
            # Process events
            if message_purpose == "event" and event_name:
                player_name = extract_player_name(body)
                
                event_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "event": event_name,
                    "player": player_name,
                    "data": body,
                    "client_ip": client_ip
                }
                
                minecraft_data["events"].append(event_entry)
                minecraft_data["stats"]["total_events"] += 1
                
                # Update player data
                if player_name and player_name not in minecraft_data["players"]:
                    minecraft_data["players"][player_name] = {
                        "first_seen": datetime.now().isoformat(),
                        "event_count": 0,
                        "messages": 0,
                        "blocks_placed": 0,
                        "blocks_broken": 0,
                        "last_position": {"x": "?", "y": "?", "z": "?"}
                    }
                
                if player_name and player_name in minecraft_data["players"]:
                    minecraft_data["players"][player_name]["event_count"] += 1
                    minecraft_data["players"][player_name]["last_seen"] = datetime.now().isoformat()
                
                timestamp_str = datetime.now().strftime("%H:%M:%S")
                
                # Track player position
                if event_name in ["PlayerTransform", "PlayerTravelled"]:
                    player_data = body.get("player", {})
                    if isinstance(player_data, dict):
                        x, y, z = extract_position(player_data, "position")
                        if x is not None and player_name:
                            player_positions[player_name] = {"x": x, "y": y, "z": z}
                            minecraft_data["players"][player_name]["last_position"] = {"x": x, "y": y, "z": z}
                
                elif event_name == "PlayerMessage":
                    message_text = body.get("message", "")
                    minecraft_data["stats"]["messages"] += 1
                    if player_name:
                        minecraft_data["players"][player_name]["messages"] += 1
                    log_message(f"[{timestamp_str}] 💬 CHAT: {player_name}: {message_text}")
                    
                    # Process chat commands
                    if message_text.startswith("!"):
                        await process_chat_command(websocket, player_name, message_text)
                
                elif event_name == "BlockPlaced":
                    block_name, player_x, player_y, player_z = extract_block_info(body)
                    minecraft_data["stats"]["blocks_placed"] += 1
                    if player_name:
                        minecraft_data["players"][player_name]["blocks_placed"] += 1
                        if player_x is not None:
                            player_positions[player_name] = {"x": player_x, "y": player_y, "z": player_z}
                            minecraft_data["players"][player_name]["last_position"] = {"x": player_x, "y": player_y, "z": player_z}
                    
                    log_message(f"[{timestamp_str}] 🔨 PLACED: {player_name} placed {block_name} at ({player_x}, {player_y}, {player_z})")
                
                elif event_name == "BlockBroken":
                    block_name, player_x, player_y, player_z = extract_block_info(body)
                    minecraft_data["stats"]["blocks_broken"] += 1
                    if player_name:
                        minecraft_data["players"][player_name]["blocks_broken"] += 1
                        if player_x is not None:
                            player_positions[player_name] = {"x": player_x, "y": player_y, "z": player_z}
                            minecraft_data["players"][player_name]["last_position"] = {"x": player_x, "y": player_y, "z": player_z}
                    
                    log_message(f"[{timestamp_str}] ⛏️  BROKEN: {player_name} broke {block_name} at ({player_x}, {player_y}, {player_z})")
                
                elif event_name == "PlayerJoin":
                    log_message(f"[{timestamp_str}] ✅ JOIN: {player_name} joined")
                    await send_command(websocket, f'tellraw {player_name} {{"rawtext":[{{"text":"§aWelcome! Type !help for commands."}}]}}')
                
                elif event_name == "PlayerLeave":
                    log_message(f"[{timestamp_str}] ❌ LEAVE: {player_name} left")
                    if player_name in player_positions:
                        del player_positions[player_name]
                
                elif event_name not in ["PlayerTransform", "PlayerTravelled"]:
                    log_message(f"[{timestamp_str}] 📌 EVENT: {event_name} by {player_name or 'System'}")
                
                # Save data periodically
                if minecraft_data["stats"]["total_events"] % 10 == 0:
                    save_data()
                    log_message(f"[{timestamp_str}] 💾 Data saved ({minecraft_data['stats']['total_events']} events)")
    
    except websockets.exceptions.ConnectionClosed:
        log_message(f"[-] Connection closed from {client_ip}")
    except Exception as e:
        log_message(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        command_task.cancel()
        log_message(f"[-] Disconnection from {client_ip}")
        save_data()
        log_message(f"Data saved to: {DATA_FILE}")

async def main():
    """Main server function."""
    local_ip = get_local_ip()
    port = 19131
    
    print("=" * 60, flush=True)
    print("MINECRAFT DATA CAPTURE SERVER WITH COMMANDS", flush=True)
    print("=" * 60, flush=True)
    print(f"Server IP: {local_ip}", flush=True)
    print(f"Port: {port}", flush=True)
    print(f"Data file: {DATA_FILE}", flush=True)
    print(f"Command file: {COMMAND_FILE}", flush=True)
    print(f"Structures file: {STRUCTURES_FILE}", flush=True)
    print("=" * 60, flush=True)
    print(f"To connect: /connect {local_ip}:{port}", flush=True)
    print("=" * 60, flush=True)
    print("\nIn-Game Commands:", flush=True)
    print("  !help       - Show commands", flush=True)
    print("  !stats      - Show your statistics", flush=True)
    print("  !time       - Change time (day/night/noon)", flush=True)
    print("  !weather    - Change weather (clear/rain/thunder)", flush=True)
    print("  !gamemode   - Change game mode", flush=True)
    print("  !build      - Build a structure at your location", flush=True)
    print("  !structures - List available structures", flush=True)
    print("\nWeb interface can also send commands!", flush=True)
    print("=" * 60, flush=True)
    
    # Initialize command file
    with open(COMMAND_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)
    
    save_data()
    
    try:
        server = await websockets.serve(handler, local_ip, port)
        print("\n[OK] Server is running!", flush=True)
        
        await asyncio.Future()
    except KeyboardInterrupt:
        print("\n[STOP] Shutting down...", flush=True)
        save_data()
        print(f"[SAVED] Data saved to: {DATA_FILE}", flush=True)
        print(f"[STATS] Total events: {minecraft_data['stats']['total_events']}", flush=True)
        print(f"[OUT] Commands sent: {minecraft_data['stats']['commands_sent']}", flush=True)
        print(f"[OK] Commands successful: {minecraft_data['stats']['commands_successful']}", flush=True)
        print(f"[BUILD] Structures built: {minecraft_data['stats']['structures_built']}", flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOP] Server stopped", flush=True)