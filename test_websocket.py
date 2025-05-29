import asyncio
import websockets
import json
from datetime import datetime

print(f"System time: {datetime.now()}")
print("Starting test WebSocket server...")

async def handle_connection(websocket, path):
    print(f"New connection from: {websocket.remote_address}")
    try:
        # Send a test message
        await websocket.send(json.dumps({"message": "Connected to test server"}))
        
        # Listen for messages
        async for message in websocket:
            print(f"Received: {message}")
            # Echo back
            await websocket.send(json.dumps({"echo": message}))
    except Exception as e:
        print(f"Connection error: {e}")

async def main():
    print("Creating server on port 3000...")
    try:
        async with websockets.serve(handle_connection, "0.0.0.0", 3000):
            print("Server is running on 0.0.0.0:3000")
            print("Try connecting from Minecraft with: /connect <your-ip>:3000")
            await asyncio.Future()  # run forever
    except Exception as e:
        print(f"Failed to start server: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped")