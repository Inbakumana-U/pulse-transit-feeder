import asyncio
import json
from datetime import datetime, timezone
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connected clients
clients = set()

class CommuterRequest(BaseModel):
    drop_lat: float
    drop_lng: float
    passenger_name: str

# Example transit hub coordinates for later reference in frontend
TRANSIT_HUB = [12.9784, 77.6408]

import uuid
import math

async def broadcast_updates():
    while True:
        if clients:
            # Generate mock live updates
            update_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "activePassengers": random.randint(1500, 3000),
                "fleetCounters": random.randint(80, 150),
            }

            # Generate new passenger request
            # 2 to 5 km radius, roughly 1 deg lat/lng = 111 km
            # so 2 to 5 km = 0.018 to 0.045 degrees
            distance_deg = random.uniform(0.018, 0.045)
            angle = random.uniform(0, 2 * math.pi)
            lat = TRANSIT_HUB[0] + distance_deg * math.cos(angle)
            lng = TRANSIT_HUB[1] + distance_deg * math.sin(angle)

            passenger_data = {
                "type": "passenger_ping",
                "passenger_id": str(uuid.uuid4()),
                "lat": lat,
                "lng": lng,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "WAITING_FOR_MATCH"
            }
            update_data["new_passenger"] = passenger_data

            message = json.dumps(update_data)

            # Broadcast to all connected clients
            for client in list(clients):
                try:
                    await client.send_text(message)
                except Exception as e:
                    print(f"Error broadcasting to client: {e}")
                    clients.remove(client)

        # Broadcast every 1.5 to 3 seconds
        await asyncio.sleep(random.uniform(1.5, 3.0))

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
        clients.discard(websocket)
    except Exception as e:
        print(f"Connection error: {e}")
        clients.discard(websocket)

@app.post("/api/commuter-request")
async def create_commuter_request(req: CommuterRequest):
    passenger_data = {
        "type": "passenger_ping",
        "passenger_id": str(uuid.uuid4()),
        "lat": req.drop_lat,
        "lng": req.drop_lng,
        "passenger_name": req.passenger_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "WAITING_FOR_MATCH",
        "source": "manual"
    }

    update_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "new_passenger": passenger_data
    }

    message = json.dumps(update_data)

    # Broadcast to all connected clients
    for client in list(clients):
        try:
            await client.send_text(message)
        except Exception as e:
            print(f"Error broadcasting manual passenger to client: {e}")
            clients.remove(client)

    return {"status": "success", "passenger_id": passenger_data["passenger_id"]}

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Pulse Transit Feeder API"}
