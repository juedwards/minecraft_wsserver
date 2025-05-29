import asyncio
import websockets
import json
import os
from uuid import uuid4
from datetime import datetime
import threading

# ========================================================================
# MINECRAFT WEBSOCKET DATA CAPTURE SERVER
# ========================================================================
# This server connects to Minecraft Education Edition via WebSockets and
# captures ALL player actions and events into a timestamped JSON file.
# 
# HOW IT WORKS:
# 1. Minecraft Education connects to this server using /connect command
# 2. Server subscribes to all Minecraft events (player actions, blocks, etc)
# 3. Every action is captured and saved to a JSON file in real-time
# 4. Multiple players can connect simultaneously
# 5. All data is saved in the /data/ folder
# ========================================================================

# List of all Minecraft events we want to capture
# These events cover player actions, world changes, and game mechanics
ALL_EVENTS = [
    "PlayerMessage",      # When a player sends a chat message
    "PlayerTravelled",    # When a player moves
    "PlayerTransform",    # When a player's position/rotation changes
    "PlayerTeleported",   # When a player teleports
    "BlockBroken",        # When a player breaks a block
    "BlockPlaced",        # When a player places a block
    "ItemAcquired",       # When a player picks up an item
    "ItemCrafted",        # When a player crafts an item
    "ItemDestroyed",      # When an item is destroyed
    "ItemDropped",        # When a player drops an item
    "ItemEnchanted",      # When a player enchants an item
    "ItemSmelted",        # When an item is smelted in a furnace
    "ItemUsed",           # When a player uses an item
    "PlayerJoin",         # When a player joins the world
    "PlayerLeave",        # When a player leaves the world
    "PlayerDied",         # When a player dies
    "MobKilled",          # When a mob is killed
    "MobSpawned",         # When a mob spawns
    "ProjectileHit",      # When a projectile hits something
    "CommandExecuted",    # When a command is executed
    "WorldLoaded",        # When a world is loaded
    "WorldUnloaded"       # When a world is unloaded
]

class MinecraftDataCapture:
    """
    Main class responsible for capturing and storing Minecraft data.
    This class handles:
    - Creating and managing the JSON file in /data/ folder
    - Thread-safe data operations
    - Tracking connected players
    - Organizing events by player and timestamp
    """
    
    def __init__(self):
        """
        Initialize the data capture system.
        Creates a new JSON file with timestamp in the filename.
        Ensures the /data/ folder exists.
        """
        # Ensure the /data/ folder exists
        self.data_folder = "/data"
        if not os.path.exists(self.data_folder):
            try:
                os.makedirs(self.data_folder)
                print(f"Created data folder: {self.data_folder}")
            except PermissionError:
                # If we can't create /data/ at root, try relative path
                self.data_folder = "data"
                if not os.path.exists(self.data_folder):
                    os.makedirs(self.data_folder)
                print(f"Using relative data folder: {self.data_folder}")
        
        # Create filename with format: MinecraftDataHHMMDDMMYY.json
        # Example: MinecraftData004129052025.json for 00:41 on May 29, 2025
        timestamp = datetime.now().strftime("%H%M%d%m%y")
        self.filename = os.path.join(self.data_folder, f"MinecraftData{timestamp}.json")
        
        # Main data structure that will be saved to JSON
        self.data = {
            "server_start_time": datetime.now().isoformat(),  # When server started
            "server_user": os.getenv('USER', os.getenv('USERNAME', 'unknown')),  # User running the server
            "players": {},  # Dictionary of all players and their events
            "events": []    # List of all events in chronological order
        }
        
        # Thread lock to prevent data corruption when multiple players act simultaneously
        self.lock = threading.Lock()
        
        # Set to track currently connected players
        self.connected_players = set()
        
        # Create the initial JSON file
        self.save_data()
        print(f"Data will be saved to: {self.filename}")
    
    def save_data(self):
        """
        Save the current data to the JSON file.
        Uses thread lock to ensure data integrity.
        Called after every event to prevent data loss.
        """
        with self.lock:  # Acquire lock to prevent concurrent writes
            try:
                with open(self.filename, 'w') as f:
                    # Write JSON with nice formatting (indent=2)
                    json.dump(self.data, f, indent=2)
            except Exception as e:
                print(f"Error saving data to {self.filename}: {e}")
    
    def add_event(self, event_data, player_name=None):
        """
        Add a new event to the data structure.
        
        Args:
            event_data (dict): The event information from Minecraft
            player_name (str, optional): Name of the player who triggered the event
        """
        with self.lock:  # Thread-safe operation
            # Create event entry with timestamp
            event_entry = {
                "timestamp": datetime.now().isoformat(),
                "event": event_data
            }
            
            # Add to the master events list (all events from all players)
            self.data["events"].append(event_entry)
            
            # If this event is associated with a specific player
            if player_name:
                # Create player entry if this is their first event
                if player_name not in self.data["players"]:
                    self.data["players"][player_name] = {
                        "first_seen": datetime.now().isoformat(),
                        "events": []
                    }
                # Add event to player's personal event list
                self.data["players"][player_name]["events"].append(event_entry)
        
        # Save immediately to prevent data loss
        self.save_data()
    
    def add_player_connection(self, player_name):
        """
        Track when a player connects to the server.
        Updates the active players list and logs the connection event.
        """
        self.connected_players.add(player_name)
        connection_event = {
            "type": "PlayerConnection",
            "player": player_name,
            "action": "connected",
            "active_players": list(self.connected_players)  # Current list of all connected players
        }
        self.add_event(connection_event, player_name)
    
    def remove_player_connection(self, player_name):
        """
        Track when a player disconnects from the server.
        Updates the active players list and logs the disconnection event.
        """
        self.connected_players.discard(player_name)  # Remove player (discard doesn't error if not present)
        disconnection_event = {
            "type": "PlayerConnection",
            "player": player_name,
            "action": "disconnected",
            "active_players": list(self.connected_players)  # Updated list after disconnection
        }
        self.add_event(disconnection_event, player_name)

# Global instance of data capture (shared across all connections)
data_capture = None

async def subscribe_to_events(websocket):
    """
    Subscribe to all Minecraft events we want to capture.
    This tells Minecraft to send us notifications when these events occur.
    
    Args:
        websocket: The WebSocket connection to Minecraft
    """
    for event_name in ALL_EVENTS:
        # Create subscription packet in Minecraft's required format
        subscribe_packet = {
            "header": {
                "version": 1,                        # Protocol version
                "requestId": str(uuid4()),           # Unique ID for this request
                "messageType": "commandRequest",     # Type of message
                "messagePurpose": "subscribe"        # We want to subscribe to events
            },
            "body": {
                "eventName": event_name  # The specific event to subscribe to
            }
        }
        # Send subscription request to Minecraft
        await websocket.send(json.dumps(subscribe_packet))
        print(f"Subscribed to: {event_name}")

async def process_message(json_message, websocket):
    """
    Process and capture all incoming messages from Minecraft.
    This is called every time Minecraft sends us data.
    
    Args:
        json_message: The message from Minecraft (string or dict)
        websocket: The WebSocket connection to Minecraft
    """
    global data_capture
    
    try:
        # Parse the message if it's a string, otherwise use as-is
        message = json.loads(json_message) if isinstance(json_message, str) else json_message
    except Exception as e:
        print(f"Error parsing message: {e}")
        return
    
    # Extract the main components of the message
    header = message.get('header', {})
    body = message.get('body', {})
    event_name = header.get('eventName', '')
    message_purpose = header.get('messagePurpose', '')
    
    # Show activity in console (helps understand what's happening)
    print(f"Event: {event_name or message_purpose} - {datetime.now().strftime('%H:%M:%S')}")
    
    # Capture the entire message for complete data preservation
    event_data = {
        "event_name": event_name,
        "message_purpose": message_purpose,
        "header": header,  # Contains metadata about the event
        "body": body       # Contains the actual event data
    }
    
    # Try to extract player name from various possible locations in the message
    player_name = None
    if 'sender' in body:  # Chat messages use 'sender'
        player_name = body['sender']
    elif 'player' in body:  # Some events use 'player'
        player_name = body['player']
    elif event_name == 'PlayerJoin' and 'properties' in body:  # Join events have nested structure
        player_name = body['properties'].get('PlayerName')
    
    # Track player connections/disconnections
    if event_name == 'PlayerJoin' and player_name:
        data_capture.add_player_connection(player_name)
    elif event_name == 'PlayerLeave' and player_name:
        data_capture.remove_player_connection(player_name)
    
    # Add this event to our data capture
    data_capture.add_event(event_data, player_name)
    
    # Special console output for important events (helps with monitoring)
    if event_name == 'PlayerMessage':
        print(f"  > Player {player_name} said: {body.get('message', '')}")
    elif event_name == 'BlockBroken':
        print(f"  > {player_name} broke: {body.get('block', 'unknown')} at {body.get('blockPos', {})}")
    elif event_name == 'BlockPlaced':
        print(f"  > {player_name} placed: {body.get('block', 'unknown')} at {body.get('blockPos', {})}")

async def handle_client(websocket, path, client_id):
    """
    Handle an individual client connection from Minecraft.
    Each connected Minecraft instance gets its own handler.
    
    Args:
        websocket: The WebSocket connection to this specific client
        path: The URL path used for connection (usually just "/")
        client_id: Unique identifier for this client connection
    """
    global data_capture
    
    print(f'Client {client_id} connected from Minecraft')
    
    # Subscribe this client to all events we want to capture
    await subscribe_to_events(websocket)
    
    # Log the WebSocket connection itself as an event
    connection_event = {
        "type": "WebSocketConnection",
        "client_id": client_id,
        "action": "connected",
        "path": path
    }
    data_capture.add_event(connection_event)
    
    try:
        # Keep processing messages until the connection closes
        async for msg in websocket:
            await process_message(msg, websocket)
    except websockets.exceptions.ConnectionClosed:
        # Normal disconnection
        print(f'Client {client_id} disconnected from Minecraft')
        # Log disconnection event
        disconnection_event = {
            "type": "WebSocketConnection",
            "client_id": client_id,
            "action": "disconnected"
        }
        data_capture.add_event(disconnection_event)
    except Exception as e:
        # Unexpected error
        print(f'Error with client {client_id}: {e}')

async def mineproxy(websocket, path):
    """
    Main entry point for each Minecraft connection.
    Creates a unique ID for the client and passes to handler.
    
    Args:
        websocket: The WebSocket connection from Minecraft
        path: The URL path (provided by websockets library)
    """
    # Generate a short unique ID for this client (first 8 chars of UUID)
    client_id = str(uuid4())[:8]
    await handle_client(websocket, path, client_id)

async def start_server():
    """
    Initialize and start the WebSocket server.
    This is the main function that sets everything up.
    """
    global data_capture
    
    # Create the data capture instance
    data_capture = MinecraftDataCapture()
    
    # Display startup information
    print('=' * 60)
    print('Minecraft Data Capture Server')
    print('=' * 60)
    print(f'Data folder: {data_capture.data_folder}')
    print(f'Data file: {data_capture.filename}')
    print(f'Server user: {data_capture.data["server_user"]}')
    print('Starting WebSocket server on localhost:3000...')
    
    # Create the WebSocket server
    server = await websockets.serve(
        mineproxy,           # Function to handle each connection
        "localhost",         # Host address (localhost = this computer only)
        3000,               # Port number (Minecraft uses 3000 by default)
        # Server configuration:
        max_size=10 * 1024 * 1024,  # Allow messages up to 10MB
        max_queue=1000               # Queue up to 1000 messages
    )
    
    print('Server started successfully!')
    print('On Minecraft Education, use: /connect localhost:3000')
    print('=' * 60)
    print('Capturing all player actions...')
    print()
    
    # Keep server running until interrupted
    await server.wait_closed()

# ========================================================================
# MAIN PROGRAM ENTRY POINT
# ========================================================================
if __name__ == "__main__":
    try:
        # Start the async server
        asyncio.run(start_server())
    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully
        print("\nServer stopped by user")
        if data_capture:
            print(f"Data saved to: {data_capture.filename}")