import asyncio
import json
from datetime import datetime, timezone
import random
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sklearn.cluster import DBSCAN
import numpy as np
import httpx
import uuid
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store connected clients
clients = set()

# Live passenger pool (unassigned passengers)
passenger_pool = {}

class CommuterRequest(BaseModel):
    drop_lat: float
    drop_lng: float
    passenger_name: str

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

            # Add to global pool
            passenger_pool[passenger_data["passenger_id"]] = passenger_data

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

async def route_dispatcher():
    # Colors for routes
    ROUTE_COLORS = ["#ef4444", "#3b82f6", "#eab308", "#d946ef", "#06b6d4"]
    color_index = 0

    while True:
        await asyncio.sleep(15)
        if not clients or len(passenger_pool) == 0:
            continue

        print(f"Running route dispatcher on {len(passenger_pool)} unassigned passengers...")

        # Extract passengers
        p_ids = list(passenger_pool.keys())
        coords = np.array([[passenger_pool[pid]["lat"], passenger_pool[pid]["lng"]] for pid in p_ids])

        # DBSCAN clustering. roughly 2km radius epsilon in degrees ~ 0.018
        clustering = DBSCAN(eps=0.018, min_samples=3).fit(coords)
        labels = clustering.labels_

        # Process each valid cluster (label != -1)
        routes = []
        assigned_pids = []

        for label in set(labels):
            if label == -1:
                continue

            cluster_pids = [p_ids[i] for i, l in enumerate(labels) if l == label]
            if len(cluster_pids) < 3:
                continue

            # Limit to 6-8 riders per route (shuttle capacity)
            cluster_pids = cluster_pids[:8]
            assigned_pids.extend(cluster_pids)

            # Sort by distance from hub (nearest neighbor heuristic)
            def dist_from_hub(pid):
                return (passenger_pool[pid]["lat"] - TRANSIT_HUB[0])**2 + (passenger_pool[pid]["lng"] - TRANSIT_HUB[1])**2

            cluster_pids.sort(key=dist_from_hub)

            # Construct OSRM request string: hub -> p1 -> p2 -> ... -> pn
            coords_str = f"{TRANSIT_HUB[1]},{TRANSIT_HUB[0]};"
            coords_str += ";".join([f'{passenger_pool[pid]["lng"]},{passenger_pool[pid]["lat"]}' for pid in cluster_pids])

            osrm_url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?geometries=geojson&overview=full"

            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(osrm_url)
                    data = resp.json()

                    if data.get("code") == "Ok":
                        route_color = ROUTE_COLORS[color_index % len(ROUTE_COLORS)]
                        color_index += 1

                        route_geometry = data["routes"][0]["geometry"]

                        for pid in cluster_pids:
                            passenger_pool[pid]["status"] = "ALLOCATED"
                            passenger_pool[pid]["route_color"] = route_color

                        routes.append({
                            "route_id": str(uuid.uuid4()),
                            "geometry": route_geometry,
                            "color": route_color,
                            "passengers": cluster_pids
                        })
            except Exception as e:
                print(f"OSRM routing failed: {e}")

        # Remove allocated passengers from pool
        for pid in assigned_pids:
            del passenger_pool[pid]

        if routes:
            # Broadcast new routes
            dispatch_msg = json.dumps({
                "type": "route_dispatch",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "routes": routes
            })

            for client in list(clients):
                try:
                    await client.send_text(dispatch_msg)
                except Exception:
                    pass

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_updates())
    asyncio.create_task(route_dispatcher())

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

    # Add to global pool
    passenger_pool[passenger_data["passenger_id"]] = passenger_data

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
