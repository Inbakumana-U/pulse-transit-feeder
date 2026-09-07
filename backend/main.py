import asyncio
import json
from datetime import datetime, timezone
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

# Store connected clients
clients = set()

# Example transit hub coordinates for later reference in frontend
TRANSIT_HUB = [12.9784, 77.6408]

async def broadcast_updates():
    while True:
        if clients:
            # Generate mock live updates
            update_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "activePassengers": random.randint(1500, 3000),
                "fleetCounters": random.randint(80, 150),
            }
            message = json.dumps(update_data)

            # Broadcast to all connected clients
            for client in list(clients):
                try:
                    await client.send_text(message)
                except Exception as e:
                    print(f"Error broadcasting to client: {e}")
                    clients.remove(client)

        # Broadcast every 2 seconds
        await asyncio.sleep(2)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_updates())

@app.websocket("/ws/transit-stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            # Keep connection open and wait for client to disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        clients.remove(websocket)
    except Exception as e:
        print(f"Connection error: {e}")
        clients.discard(websocket)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Pulse Transit Feeder API"}
