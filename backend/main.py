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

# Global Metrics State
metrics_state = {
    "cumulative_vmt_saved": 0.0,
    "total_wait_time_sec": 0.0,
    "wait_time_count": 0,
    "active_shuttles": []
}

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
                    clients.discard(client)

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
                        assigned_pids.extend(cluster_pids)
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
                        # Metric calculations
                        # Direct distance baseline (Hub -> Dropoff -> Hub for each passenger)
                        baseline_distance = 0.0
                        for pid in cluster_pids:
                            p_lat = passenger_pool[pid]["lat"]
                            p_lng = passenger_pool[pid]["lng"]
                            # Haversine distance could be used, or we just rely on OSRM distance.
                            # Let's approximate baseline as direct cartesian * 111km for now if we don't query OSRM for each.
                            # OSRM returns distance in meters.
                            # We can also do a quick rough approx for baseline:
                            dist_deg = math.sqrt((p_lat - TRANSIT_HUB[0])**2 + (p_lng - TRANSIT_HUB[1])**2)
                            baseline_distance += (dist_deg * 111000) * 2 # round trip meters

                            # Wait time
                            req_time = datetime.fromisoformat(passenger_pool[pid]["timestamp"])
                            wait_sec = (datetime.now(timezone.utc) - req_time).total_seconds()
                            metrics_state["total_wait_time_sec"] += wait_sec
                            metrics_state["wait_time_count"] += 1

                        shared_distance = data["routes"][0]["distance"] # in meters
                        vmt_saved_km = (baseline_distance - shared_distance) / 1000.0
                        if vmt_saved_km > 0:
                            metrics_state["cumulative_vmt_saved"] += vmt_saved_km

                        route_duration_sec = data["routes"][0]["duration"]

                        shuttle_id = str(uuid.uuid4())
                        metrics_state["active_shuttles"].append({
                            "id": shuttle_id,
                            "color": route_color,
                            "capacity": 8,
                            "filled_seats": len(cluster_pids),
                            "duration_sec": route_duration_sec,
                            "start_time": datetime.now(timezone.utc).isoformat()
                        })

                        routes.append({
                            "route_id": shuttle_id,
                            "geometry": route_geometry,
                            "color": route_color,
                            "passengers": cluster_pids
                        })
            except Exception as e:
                print(f"OSRM routing failed: {e}")

        # Clean up active shuttles (remove if duration has passed)
        now_utc = datetime.now(timezone.utc)
        metrics_state["active_shuttles"] = [
            s for s in metrics_state["active_shuttles"]
            if (now_utc - datetime.fromisoformat(s["start_time"])).total_seconds() < s["duration_sec"]
        ]

        # Remove allocated passengers from pool
        for pid in assigned_pids:
            del passenger_pool[pid]

        if routes or True: # Always broadcast to update metrics
            # Calculate dynamic metrics
            avg_wait = 0
            if metrics_state["wait_time_count"] > 0:
                avg_wait = metrics_state["total_wait_time_sec"] / metrics_state["wait_time_count"]

            active_utilization = 0.0
            if metrics_state["active_shuttles"]:
                total_seats = sum(s["capacity"] for s in metrics_state["active_shuttles"])
                filled_seats = sum(s["filled_seats"] for s in metrics_state["active_shuttles"])
                active_utilization = (filled_seats / total_seats) * 100

            # Broadcast new routes and metrics
            dispatch_msg = json.dumps({
                "type": "route_dispatch",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "routes": routes,
                "metrics": {
                    "vmt_saved_km": metrics_state["cumulative_vmt_saved"],
                    "utilization_pct": active_utilization,
                    "avg_wait_sec": avg_wait,
                    "active_shuttles": metrics_state["active_shuttles"]
                }
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
            clients.discard(client)

    return {"status": "success", "passenger_id": passenger_data["passenger_id"]}

@app.post("/api/flush-stream")
async def flush_stream():
    global passenger_pool, metrics_state
    passenger_pool.clear()
    metrics_state = {
        "cumulative_vmt_saved": 0.0,
        "total_wait_time_sec": 0.0,
        "wait_time_count": 0,
        "active_shuttles": []
    }

    flush_msg = json.dumps({
        "type": "flush",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    for client in list(clients):
        try:
            await client.send_text(flush_msg)
        except Exception:
            pass

    return {"status": "flushed"}

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Pulse Transit Feeder API"}
