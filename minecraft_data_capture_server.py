import asyncio
import websockets
import json
import os
from uuid import uuid4
from datetime import datetime
import sys

# Force unbuffered output
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

# ========================================================================
# MINECRAFT WEBSOCKET DATA CAPTURE SERVER
# ========================================================================

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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(self.data_folder, f"MinecraftData_{timestamp}.json")
        
        # Main data structure
        self.data = {
            "server_start_time": datetime.now().isoformat(),
            "server_user": os.getenv('USERNAME', 'unknown'),
            "server_port": port,
            "events": [],
            "messages": []
        }
        
        # Create the initial JSON file
        self.save_data()
        print(f"Data will be saved to: {self.filename}", flush=True)
    
    def save_data(self):
        """Save the current data to the JSON file."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Error saving data: {e}", flush=True)

    def add_message(self, message, direction="received"):
        """Add a message to the data structure."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "direction": direction,
            "message": message
        }
        self.data["messages"].append(entry)
        
        # Extract event if present
        if isinstance(message, dict):
            header = message.get("header", {})
            if header.get("eventName"):
                self.data["events"].append(entry)
        
        self.save_data()

# Global instance
data_capture = None

async def handle_connection(websocket, path):
    """Handle a WebSocket connection from Minecraft."""
    global data_capture
    
    print(f"\n>>> New connection from {websocket.remote_address}", flush=True)
    print(">>> Connection established! Now run commands in Minecraft to see events.", flush=True)
    print(">>> For example, try: /say Hello World", flush=True)
    
    try:
        # First, let's subscribe to a simple event to test
        print("\nSubscribing to PlayerMessage event...", flush=True)
        
        subscribe_msg = {
            "header": {
                "requestId": str(uuid4()),
                "messagePurpose": "subscribe",
                "version": 1,
                "messageType": "commandRequest"
            },
            "body": {
                "eventName": "PlayerMessage"
            }
        }
        
        await websocket.send(json.dumps(subscribe_msg))
        data_capture.add_message(subscribe_msg, "sent")
        print("Subscription sent! Waiting for messages...", flush=True)
        
        # Process all incoming messages
        async for message in websocket:
            try:
                data = json.loads(message)
                data_capture.add_message(data, "received")
                
                header = data.get("header", {})
                body = data.get("body", {})
                
                # Log everything for debugging
                msg_type = header.get("messageType", "")
                msg_purpose = header.get("messagePurpose", "")
                event_name = header.get("eventName", "")
                
                print(f"\n[MESSAGE] Type: {msg_type}, Purpose: {msg_purpose}, Event: {event_name}", flush=True)
                
                if msg_purpose == "commandResponse":
                    status = body.get("statusCode", -1)
                    print(f"  Response Status: {status} - {body.get('statusMessage', 'OK')}", flush=True)
                
                if event_name:
                    print(f"  Event Data: {json.dumps(body, indent=2)}", flush=True)
                    
                    # Special handling for PlayerMessage
                    if event_name == "PlayerMessage":
                        sender = body.get("sender", "Unknown")
                        msg_text = body.get("message", "")
                        print(f"\n*** CHAT: {sender}: {msg_text} ***", flush=True)
                
            except json.JSONDecodeError:
                print(f"Failed to parse message: {message}", flush=True)
            except Exception as e:
                print(f"Error processing message: {e}", flush=True)
            
    except websockets.exceptions.ConnectionClosed as e:
        print(f"\n<<< Connection closed: {e}", flush=True)
    except Exception as e:
        print(f"\n[ERROR] {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        # Save data on disconnect
        if data_capture:
            data_capture.save_data()
            print(f"Data saved to: {data_capture.filename}", flush=True)

async def start_server():
    """Initialize and start the WebSocket server."""
    global data_capture
    
    # Initialize data capture
    data_capture = MinecraftDataCapture(3000)
    
    # Display startup information
    print('=' * 60, flush=True)
    print('MINECRAFT WEBSOCKET SERVER - SIMPLE TEST', flush=True)
    print('=' * 60, flush=True)
    print(f'Server Time: {datetime.now()}', flush=True)
    print(f'Data file: {data_capture.filename}', flush=True)
    print('=' * 60, flush=True)
    
    # Start the server
    async with websockets.serve(handle_connection, "0.0.0.0", 3000):
        print('Server running on port 3000', flush=True)
        print('=' * 60, flush=True)
        print('Instructions:', flush=True)
        print('', flush=True)
        print('1. In Minecraft Education Edition, run:', flush=True)
        print('   /connect 192.168.4.242:3000', flush=True)
        print('', flush=True)
        print('2. After connecting, try sending a chat message:', flush=True)
        print('   /say Hello World', flush=True)
        print('   or just type in chat: Hello World', flush=True)
        print('', flush=True)
        print('3. You should see the message appear here!', flush=True)
        print('=' * 60, flush=True)
        print('Waiting for connections...', flush=True)
        
        # Run forever
        await asyncio.Future()

# ========================================================================
# MAIN PROGRAM ENTRY POINT
# ========================================================================
if __name__ == "__main__":
    try:
        # First, let's check the system time
        print(f"System time check: {datetime.now()}", flush=True)
        if datetime.now().year > 2024:
            print("WARNING: Your system date appears to be incorrect!", flush=True)
            print("This might cause issues with SSL certificates and connections.", flush=True)
            print("Consider fixing your system date before proceeding.", flush=True)
            print("", flush=True)
        
        asyncio.run(start_server())
    except KeyboardInterrupt:
        print("\n\nServer stopped by user", flush=True)
        if data_capture:
            print(f"Data saved to: {data_capture.filename}", flush=True)