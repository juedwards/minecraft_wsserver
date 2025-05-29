import asyncio
import websockets
import json
import os
from uuid import uuid4
from datetime import datetime
import threading
import sys

# Force unbuffered output
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

# ========================================================================
# MINECRAFT WEBSOCKET DATA CAPTURE SERVER
# ========================================================================

# List of all Minecraft events we want to capture
ALL_EVENTS = [
    "AgentCommand", "AgentCreated", "ApiInit", "AppPaused", "AppResumed", "AppSuspended",
    "AwardAchievement", "BlockBroken", "BlockPlaced", "BoardTextUpdated", "BossKilled",
    "CameraUsed", "CauldronUsed", "ChunkChanged", "ChunkLoaded", "ChunkUnloaded",
    "ConfigurationChanged", "ConnectionFailed", "CraftingSessionCompleted", "EndOfDay",
    "EntitySpawned", "FileTransmissionCancelled", "FileTransmissionCompleted", "FileTransmissionStarted",
    "FirstTimeClientOpen", "FocusGained", "FocusLost", "GameSessionComplete", "GameSessionStart",
    "HardwareInfo", "HasNewContent", "ItemAcquired", "ItemCrafted", "ItemDestroyed", "ItemDropped",
    "ItemEnchanted", "ItemSmelted", "ItemUsed", "JoinCanceled", "JukeboxUsed", "LicenseCensus",
    "MascotCreated", "MenuShown", "MobInteracted", "MobKilled", "MultiplayerConnectionStateChanged",
    "MultiplayerRoundEnd", "MultiplayerRoundStart", "NpcPropertiesUpdated", "OptionsUpdated",
    "performanceMetrics", "PackImportStage", "PlayerBounced", "PlayerDied", "PlayerJoin",
    "PlayerLeave", "PlayerMessage", "PlayerTeleported", "PlayerTransform", "PlayerTravelled",
    "PortalBuilt", "PortalUsed", "PortfolioExported", "PotionBrewed", "PurchaseAttempt",
    "PushNotificationOpened", "PushNotificationPermission", "PushNotificationReceived",
    "RegionalPopup", "RespondedToAcceptContent", "ScreenChanged", "ScreenHeartbeat", "SignInToEdu",
    "SignInToXboxLive", "SignOutOfXboxLive", "SpecialMobBuilt", "StartClient", "StartWorld",
    "TextToSpeechToggled", "UgcDownloadCompleted", "UgcDownloadStarted", "UploadSkin",
    "VehicleExited", "WorldExported", "WorldFilesListed", "WorldGenerated", "WorldLoaded", "WorldUnloaded"
]

class MinecraftDataCapture:
    """Main class responsible for capturing and storing Minecraft data."""
    
    def __init__(self, port=3000):
        """Initialize the data capture system."""
        self.port = port
        
        # Ensure the data folder exists
        self.data_folder = "data"
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder)
            print(f"Created data folder: {self.data_folder}", flush=True)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime("%H%M%d%m%y")
        self.filename = os.path.join(self.data_folder, f"MinecraftData{timestamp}.json")
        
        # Main data structure
        self.data = {
            "server_start_time": datetime.now().isoformat(),
            "server_user": os.getenv('USERNAME', 'unknown'),
            "server_port": port,
            "players": {},
            "events": [],
            "stats": {
                "total_events": 0,
                "blocks_broken": 0,
                "blocks_placed": 0,
                "messages_sent": 0
            }
        }
        
        # Thread lock
        self.lock = threading.Lock()
        
        # Connected players
        self.connected_players = set()
        
        # Create the initial JSON file
        self.save_data()
        print(f"Data will be saved to: {self.filename}", flush=True)
    
    def save_data(self):
        """Save the current data to the JSON file."""
        with self.lock:
            try:
                with open(self.filename, 'w') as f:
                    json.dump(self.data, f, indent=2)
            except Exception as e:
                print(f"Error saving data: {e}", flush=True)

    def add_event(self, event_data, player_name=None):
        """Add a new event to the data structure."""
        with self.lock:
            event_entry = {
                "timestamp": datetime.now().isoformat(),
                "event": event_data
            }
            
            self.data["events"].append(event_entry)
            self.data["stats"]["total_events"] += 1
            
            # Update stats
            event_name = event_data.get("event_name", "")
            if event_name == "BlockBroken":
                self.data["stats"]["blocks_broken"] += 1
            elif event_name == "BlockPlaced":
                self.data["stats"]["blocks_placed"] += 1
            elif event_name == "PlayerMessage":
                self.data["stats"]["messages_sent"] += 1
            
            if player_name:
                if player_name not in self.data["players"]:
                    self.data["players"][player_name] = {
                        "first_seen": datetime.now().isoformat(),
                        "last_seen": datetime.now().isoformat(),
                        "events": []
                    }
                else:
                    self.data["players"][player_name]["last_seen"] = datetime.now().isoformat()
                
                self.data["players"][player_name]["events"].append(event_entry)
        
        # Save every 10 events to reduce disk I/O
        if self.data["stats"]["total_events"] % 10 == 0:
            self.save_data()

# Global instance
data_capture = None

async def subscribe_to_event(websocket, event_name):
    """Subscribe to a single Minecraft event."""
    request_id = str(uuid4())
    subscribe_msg = {
        "header": {
            "requestId": request_id,
            "messagePurpose": "subscribe",
            "version": 1,
            "messageType": "commandRequest"
        },
        "body": {
            "eventName": event_name
        }
    }
    
    await websocket.send(json.dumps(subscribe_msg))
    return request_id

async def subscribe_to_all_events(websocket):
    """Subscribe to all Minecraft events."""
    print("\nSubscribing to events...", flush=True)
    successful = 0
    
    for event_name in ALL_EVENTS:
        try:
            await subscribe_to_event(websocket, event_name)
            successful += 1
            
            # Show progress every 10 events
            if successful % 10 == 0:
                print(f"  Subscribed to {successful}/{len(ALL_EVENTS)} events...", flush=True)
            
            # Small delay between subscriptions
            await asyncio.sleep(0.01)
            
        except Exception as e:
            print(f"  Failed to subscribe to {event_name}: {e}", flush=True)
    
    print(f"\nSuccessfully subscribed to {successful} events!", flush=True)
    print("=" * 60, flush=True)
    print("Ready! Waiting for Minecraft events...", flush=True)
    print("=" * 60, flush=True)

async def process_message(websocket, message):
    """Process incoming messages from Minecraft."""
    global data_capture
    
    try:
        data = json.loads(message)
    except json.JSONDecodeError:
        return
    
    header = data.get("header", {})
    body = data.get("body", {})
    
    msg_purpose = header.get("messagePurpose", "")
    event_name = header.get("eventName", "")
    
    # Handle different message purposes
    if msg_purpose == "event":
        # This is an actual event from Minecraft
        event_data = {
            "event_name": event_name,
            "header": header,
            "body": body
        }
        
        # Extract player information
        player_name = None
        properties = body.get("properties", {})
        
        # Try different locations for player name
        if "PlayerName" in properties:
            player_name = properties["PlayerName"]
        elif "player" in body:
            player_name = body["player"]
        elif "sender" in body:
            player_name = body["sender"]
        
        # Save the event
        data_capture.add_event(event_data, player_name)
        
        # Display the event
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Format output based on event type
        if event_name == "PlayerJoin":
            print(f"[{timestamp}] [JOIN] {player_name or 'Unknown'} joined the game", flush=True)
        elif event_name == "PlayerLeave":
            print(f"[{timestamp}] [LEAVE] {player_name or 'Unknown'} left the game", flush=True)
        elif event_name == "PlayerMessage":
            msg_text = body.get("message", "")
            msg_type = body.get("type", "chat")
            print(f"[{timestamp}] [CHAT] <{player_name}> {msg_text}", flush=True)
        elif event_name == "BlockBroken":
            block = body.get("block", {})
            block_name = block.get("name", "unknown") if isinstance(block, dict) else str(block)
            print(f"[{timestamp}] [BREAK] {player_name} broke {block_name}", flush=True)
        elif event_name == "BlockPlaced":
            block = body.get("block", {})
            block_name = block.get("name", "unknown") if isinstance(block, dict) else str(block)
            print(f"[{timestamp}] [PLACE] {player_name} placed {block_name}", flush=True)
        elif event_name == "PlayerDied":
            print(f"[{timestamp}] [DEATH] {player_name} died", flush=True)
        elif event_name == "ItemCrafted":
            item = body.get("item", {})
            item_name = item.get("name", "unknown") if isinstance(item, dict) else str(item)
            print(f"[{timestamp}] [CRAFT] {player_name} crafted {item_name}", flush=True)
        elif event_name not in ["PlayerTransform", "PlayerTravelled"]:  # Skip noisy events
            print(f"[{timestamp}] [{event_name}] {player_name or ''}", flush=True)
    
    elif msg_purpose == "commandResponse":
        # Response to our subscription requests
        status_code = body.get("statusCode", -1)
        if status_code != 0:
            status_msg = body.get("statusMessage", "Unknown error")
            print(f"[RESPONSE] Command failed: {status_msg}", flush=True)

async def handle_connection(websocket, path):
    """Handle a WebSocket connection from Minecraft."""
    global data_capture
    
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    print(f"\n>>> New connection from {client_ip}", flush=True)
    
    try:
        # Subscribe to all events
        await subscribe_to_all_events(websocket)
        
        # Keep processing messages
        async for message in websocket:
            await process_message(websocket, message)
            
    except websockets.exceptions.ConnectionClosed:
        print(f"\n<<< Connection from {client_ip} closed", flush=True)
    except Exception as e:
        print(f"\n[ERROR] {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        # Save any remaining data
        if data_capture:
            data_capture.save_data()

async def start_server():
    """Initialize and start the WebSocket server."""
    global data_capture
    
    # Initialize data capture
    data_capture = MinecraftDataCapture(3000)
    
    # Display startup information
    print('=' * 60, flush=True)
    print('MINECRAFT EDUCATION EDITION - DATA CAPTURE SERVER', flush=True)
    print('=' * 60, flush=True)
    print(f'Data folder: {data_capture.data_folder}', flush=True)
    print(f'Data file: {data_capture.filename}', flush=True)
    print(f'Server port: 3000', flush=True)
    print('=' * 60, flush=True)
    
    # Start the WebSocket server
    server = await websockets.serve(
        handle_connection,
        "0.0.0.0",
        3000,
        subprotocols=[]  # Minecraft doesn't use subprotocols
    )
    
    print('Server started successfully!', flush=True)
    print('=' * 60, flush=True)
    print('To connect from Minecraft Education Edition:', flush=True)
    print('', flush=True)
    print('1. First, allow WebSocket connections:', flush=True)
    print('   /wsserver 192.168.4.242:3000', flush=True)
    print('', flush=True)
    print('2. Then connect to this server:', flush=True)
    print('   /connect 192.168.4.242:3000', flush=True)
    print('', flush=True)
    print('NOTE: You may need to use /connect multiple times', flush=True)
    print('=' * 60, flush=True)
    print('Waiting for connections...', flush=True)
    
    # Run forever
    await asyncio.Future()

# ========================================================================
# MAIN PROGRAM ENTRY POINT
# ========================================================================
if __name__ == "__main__":
    print(f"Starting server at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    
    try:
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n\nServer stopped by user", flush=True)
        if data_capture:
            data_capture.save_data()
            print(f"Data saved to: {data_capture.filename}", flush=True)
            print(f"Total events captured: {data_capture.data['stats']['total_events']}", flush=True)