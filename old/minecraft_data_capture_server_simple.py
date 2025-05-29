import asyncio
import websockets
import json
import uuid
import sys
import socket
from pathlib import Path
from datetime import datetime

# Force output to be unbuffered
import os
os.environ['PYTHONUNBUFFERED'] = '1'

print("Minecraft Data Capture Server Starting...", flush=True)

# Setup data directories
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Create timestamped files
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
DATA_FILE = DATA_DIR / f"MinecraftData_{timestamp}.json"
LOG_FILE = DATA_DIR / f"server_{timestamp}.log"

# Main data structure
minecraft_data = {
    "server_start": datetime.now().isoformat(),
    "events": [],
    "players": {},
    "stats": {
        "total_events": 0,
        "messages": 0,
        "blocks_placed": 0,
        "blocks_broken": 0
    }
}

# Events to subscribe to
MINECRAFT_EVENTS = [
    "PlayerJoin", "PlayerLeave", "PlayerMessage", "PlayerTransform", 
    "BlockPlaced", "BlockBroken", "ItemUsed", "ItemCrafted",
    "PlayerTeleported", "MobKilled", "PlayerDied", "CommandExecuted",
    "PlayerTravelled"
]

def log_message(message):
    """Log message to both console and file"""
    print(message, flush=True)
    with open(LOG_FILE, "a") as f:
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
        with DATA_FILE.open("w") as f:
            json.dump(minecraft_data, f, indent=2)
        return True
    except Exception as e:
        log_message(f"Error saving data: {e}")
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
    # Try different possible locations for player name
    player_data = body.get("player")
    
    if isinstance(player_data, dict):
        # Player name might be in player dict
        player_name = player_data.get("name") or player_data.get("PlayerName")
    else:
        player_name = player_data
    
    if not player_name:
        player_name = body.get("sender")
    if not player_name:
        properties = body.get("properties", {})
        if isinstance(properties, dict):
            player_name = properties.get("PlayerName")
    
    # Convert to string if it's not None
    if player_name:
        player_name = str(player_name)
    
    return player_name

def extract_position(data, pos_key="position"):
    """Extract position information from data."""
    pos = data.get(pos_key, {})
    
    # Try different position formats
    if isinstance(pos, dict):
        x = pos.get("x")
        y = pos.get("y") 
        z = pos.get("z")
        
        # Round to 2 decimal places if floats
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
    # Get block data
    block_data = body.get("block")
    
    # Extract block name
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
    
    # Get block position - try multiple locations
    block_x, block_y, block_z = None, None, None
    
    # Try blockPos first
    block_x, block_y, block_z = extract_position(body, "blockPos")
    
    # If no blockPos, try position at top level
    if block_x is None:
        block_x, block_y, block_z = extract_position(body, "position")
    
    # Get player position from player object
    player_x, player_y, player_z = None, None, None
    player_data = body.get("player", {})
    if isinstance(player_data, dict):
        player_x, player_y, player_z = extract_position(player_data, "position")
    
    # Format positions
    block_x = block_x if block_x is not None else "?"
    block_y = block_y if block_y is not None else "?"
    block_z = block_z if block_z is not None else "?"
    
    return block_name, block_x, block_y, block_z, player_x, player_y, player_z

def extract_item_info(body):
    """Extract item information from event body."""
    # Try 'tool' field first (as shown in your data)
    item_data = body.get("tool") or body.get("item")
    
    if isinstance(item_data, dict):
        item_name = (
            item_data.get("id") or 
            item_data.get("name") or 
            item_data.get("type")
        )
        count = item_data.get("stackSize") or item_data.get("count", 1)
    elif isinstance(item_data, str):
        item_name = item_data
        count = 1
    else:
        item_name = body.get("itemType") or body.get("itemName") or "unknown_item"
        count = body.get("count", 1)
    
    return item_name, count

# Track player positions
player_positions = {}

async def handler(websocket):
    """Handle WebSocket connections from Minecraft."""
    client_ip = websocket.remote_address[0]
    log_message(f"[+] Connection from {client_ip}")
    
    # Subscribe to all events
    for event in MINECRAFT_EVENTS:
        await subscribe_event(websocket, event)
    
    log_message(f"[{client_ip}] Subscribed to {len(MINECRAFT_EVENTS)} events")
    
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
            
            # Process events
            if message_purpose == "event" and event_name:
                # Extract player info safely
                player_name = extract_player_name(body)
                
                # Create event entry
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
                
                # Display specific events
                timestamp_str = datetime.now().strftime("%H:%M:%S")
                
                # Track player position from movement events
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
                    log_message(f"[{timestamp_str}] CHAT: {player_name}: {message_text}")
                
                elif event_name == "BlockPlaced":
                    block_name, block_x, block_y, block_z, player_x, player_y, player_z = extract_block_info(body)
                    minecraft_data["stats"]["blocks_placed"] += 1
                    if player_name:
                        minecraft_data["players"][player_name]["blocks_placed"] += 1
                        
                        # Update player position if available
                        if player_x is not None:
                            player_positions[player_name] = {"x": player_x, "y": player_y, "z": player_z}
                            minecraft_data["players"][player_name]["last_position"] = {"x": player_x, "y": player_y, "z": player_z}
                        
                        if player_x is not None:
                            log_message(f"[{timestamp_str}] PLACED: {player_name} placed {block_name} at ({block_x}, {block_y}, {block_z}) | Player at ({player_x}, {player_y}, {player_z})")
                        else:
                            log_message(f"[{timestamp_str}] PLACED: {player_name} placed {block_name} at ({block_x}, {block_y}, {block_z})")
                
                elif event_name == "BlockBroken":
                    block_name, block_x, block_y, block_z, player_x, player_y, player_z = extract_block_info(body)
                    minecraft_data["stats"]["blocks_broken"] += 1
                    if player_name:
                        minecraft_data["players"][player_name]["blocks_broken"] += 1
                        
                        # Update player position if available
                        if player_x is not None:
                            player_positions[player_name] = {"x": player_x, "y": player_y, "z": player_z}
                            minecraft_data["players"][player_name]["last_position"] = {"x": player_x, "y": player_y, "z": player_z}
                        
                        if player_x is not None:
                            log_message(f"[{timestamp_str}] BROKEN: {player_name} broke {block_name} at ({block_x}, {block_y}, {block_z}) | Player at ({player_x}, {player_y}, {player_z})")
                        else:
                            log_message(f"[{timestamp_str}] BROKEN: {player_name} broke {block_name} at ({block_x}, {block_y}, {block_z})")
                
                elif event_name == "PlayerJoin":
                    log_message(f"[{timestamp_str}] JOIN: {player_name} joined")
                
                elif event_name == "PlayerLeave":
                    log_message(f"[{timestamp_str}] LEAVE: {player_name} left")
                    # Clear position data
                    if player_name in player_positions:
                        del player_positions[player_name]
                
                elif event_name == "ItemUsed":
                    item_name, count = extract_item_info(body)
                    log_message(f"[{timestamp_str}] USED: {player_name} used {item_name}")
                
                elif event_name == "ItemCrafted":
                    item_name, count = extract_item_info(body)
                    log_message(f"[{timestamp_str}] CRAFTED: {player_name} crafted {count}x {item_name}")
                
                elif event_name == "PlayerDied":
                    cause = body.get("cause") or body.get("deathCause") or "unknown"
                    log_message(f"[{timestamp_str}] DEATH: {player_name} died - {cause}")
                
                elif event_name == "MobKilled":
                    mob = body.get("mob", {})
                    mob_type = mob.get("type") or mob.get("name") or mob.get("id") or "unknown"
                    log_message(f"[{timestamp_str}] KILL: {player_name} killed {mob_type}")
                
                elif event_name not in ["PlayerTransform", "PlayerTravelled"]:
                    # Log other events
                    log_message(f"[{timestamp_str}] EVENT: {event_name} by {player_name or 'System'}")
                
                # Save data every 5 events
                if minecraft_data["stats"]["total_events"] % 5 == 0:
                    save_data()
                    log_message(f"[{timestamp_str}] Data saved ({minecraft_data['stats']['total_events']} events)")
            
            # Handle command responses
            elif message_purpose == "commandResponse":
                status_code = body.get("statusCode", -1)
                if status_code != 0:
                    log_message(f"Command response: {body.get('statusMessage', 'Unknown error')}")
    
    except websockets.exceptions.ConnectionClosed:
        log_message(f"[-] Connection closed from {client_ip}")
    except Exception as e:
        log_message(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        log_message(f"[-] Disconnection from {client_ip}")
        save_data()
        log_message(f"Data saved to: {DATA_FILE}")

async def main():
    """Main server function."""
    local_ip = get_local_ip()
    port = 19131
    
    print("=" * 60, flush=True)
    print("MINECRAFT DATA CAPTURE SERVER", flush=True)
    print("=" * 60, flush=True)
    print(f"Server IP: {local_ip}", flush=True)
    print(f"Port: {port}", flush=True)
    print(f"Data file: {DATA_FILE}", flush=True)
    print(f"Log file: {LOG_FILE}", flush=True)
    print("=" * 60, flush=True)
    print(f"To connect: /connect {local_ip}:{port}", flush=True)
    print("=" * 60, flush=True)
    
    # Save initial data
    save_data()
    
    try:
        # Start WebSocket server
        server = await websockets.serve(handler, local_ip, port)
        print("Server is running!", flush=True)
        print("Player positions will be tracked from block events", flush=True)
        
        # Run forever
        await asyncio.Future()
    except KeyboardInterrupt:
        print("\nShutting down...", flush=True)
        save_data()
        print(f"Data saved to: {DATA_FILE}", flush=True)
        print(f"Total events: {minecraft_data['stats']['total_events']}", flush=True)
        
        # Print player stats
        if minecraft_data["players"]:
            print("\nPlayer Statistics:", flush=True)
            for player, stats in minecraft_data["players"].items():
                print(f"  {player}:", flush=True)
                print(f"    - Events: {stats.get('event_count', 0)}", flush=True)
                print(f"    - Messages: {stats.get('messages', 0)}", flush=True)
                print(f"    - Blocks placed: {stats.get('blocks_placed', 0)}", flush=True)
                print(f"    - Blocks broken: {stats.get('blocks_broken', 0)}", flush=True)
                last_pos = stats.get('last_position', {})
                print(f"    - Last position: ({last_pos.get('x', '?')}, {last_pos.get('y', '?')}, {last_pos.get('z', '?')})", flush=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped", flush=True)