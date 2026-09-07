import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMapEvents } from 'react-leaflet';
import { Activity, Users, Bus } from 'lucide-react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix Leaflet's default icon path issues with webpack/vite
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom pulsing icon for Transit Hub
const createPulseIcon = () => {
  return L.divIcon({
    className: 'custom-div-icon',
    html: `
      <div class="relative w-4 h-4">
        <div class="absolute inset-0 bg-blue-500 rounded-full"></div>
        <div class="pulse-ring"></div>
      </div>
    `,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
};

const pulseIcon = createPulseIcon();

// Custom icon for passenger pings with entry pulse animation
const createPassengerPingIcon = () => {
  return L.divIcon({
    className: 'custom-div-icon animate-ping-entry',
    html: `
      <div class="w-3 h-3 bg-emerald-400 rounded-full shadow-[0_0_10px_rgba(52,211,153,0.8)] border border-emerald-200"></div>
    `,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  });
};

const passengerPingIcon = createPassengerPingIcon();
const TRANSIT_HUB_COORDS: [number, number] = [12.9784, 77.6408];

// Map Event Listener Component
const MapClickHandler = () => {
  useMapEvents({
    click: async (e) => {
      const { lat, lng } = e.latlng;

      try {
        await fetch('http://localhost:8000/api/commuter-request', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            drop_lat: lat,
            drop_lng: lng,
            passenger_name: 'Manual Operator Drop'
          })
        });
      } catch (err) {
        console.error("Failed to post manual commuter request", err);
      }
    }
  });
  return null;
};

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [activePassengers, setActivePassengers] = useState(0);
  const [fleetCounters, setFleetCounters] = useState(0);
  const [time, setTime] = useState({ local: '', utc: '' });

  // New passenger stream state
  const [passengerPings, setPassengerPings] = useState<any[]>([]);
  const [isStreamPaused, setIsStreamPaused] = useState(false);
  const isStreamPausedRef = useRef(isStreamPaused);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    isStreamPausedRef.current = isStreamPaused;
  }, [isStreamPaused]);

  // Auto-reconnecting WebSocket
  useEffect(() => {
    let timeoutId: number;

    const connect = () => {
      // Connect to the FastAPI WebSocket endpoint
      const wsUrl = `ws://localhost:8000/ws/transit-stream`;
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.activePassengers) setActivePassengers(data.activePassengers);
          if (data.fleetCounters) setFleetCounters(data.fleetCounters);

          if (data.new_passenger && (!isStreamPausedRef.current || data.new_passenger.source === 'manual')) {
            setPassengerPings(prev => {
              // Keep only the last 50 pings to avoid overwhelming the map
              const updated = [...prev, data.new_passenger];
              if (updated.length > 50) return updated.slice(updated.length - 50);
              return updated;
            });
          }
        } catch (err) {
          console.error("Failed to parse websocket message", err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        // Try to reconnect after 3 seconds
        timeoutId = window.setTimeout(connect, 3000);
      };

      ws.onerror = (error) => {
        console.error("WebSocket error", error);
        ws.close();
      };

      wsRef.current = ws;
    };

    connect();

    return () => {
      if (timeoutId) window.clearTimeout(timeoutId);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  // Update time display
  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      setTime({
        local: now.toLocaleTimeString(),
        utc: now.toUTCString().split(' ')[4] + ' UTC',
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // Time formatter for the ticker
  const formatRelativeTime = (isoString: string) => {
    const msPerMinute = 60 * 1000;
    const msPerHour = msPerMinute * 60;

    const elapsed = Date.now() - new Date(isoString).getTime();

    if (elapsed < msPerMinute) {
       return `${Math.round(elapsed/1000)}s ago`;
    }
    else if (elapsed < msPerHour) {
       return `${Math.round(elapsed/msPerMinute)}m ago`;
    }
    return `${Math.round(elapsed/msPerHour )}h ago`;
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-200 overflow-hidden font-sans">
      {/* Live Status Header */}
      <header className="flex-none bg-slate-900 border-b border-slate-800 p-4 shadow-md z-10 flex flex-wrap justify-between items-center">
        <div className="flex items-center space-x-6">
          <h1 className="text-xl font-bold tracking-wider text-blue-400">PULSE TRANSIT</h1>
          <div className="flex flex-col">
            <span className="text-sm font-mono text-slate-300">{time.utc}</span>
            <span className="text-xs font-mono text-slate-500">Local: {time.local}</span>
          </div>
        </div>

        <div className="flex items-center space-x-8">
          {/* Active Passengers Counter */}
          <div className="flex items-center space-x-2">
            <Users size={18} className="text-emerald-400" />
            <div className="flex flex-col">
              <span className="text-xs text-slate-400 uppercase">Passengers</span>
              <span className="text-lg font-bold text-emerald-400 tabular-nums">{activePassengers.toLocaleString()}</span>
            </div>
          </div>

          {/* Fleet Counter */}
          <div className="flex items-center space-x-2">
            <Bus size={18} className="text-amber-400" />
            <div className="flex flex-col">
              <span className="text-xs text-slate-400 uppercase">Active Fleet</span>
              <span className="text-lg font-bold text-amber-400 tabular-nums">{fleetCounters.toLocaleString()}</span>
            </div>
          </div>

          {/* Pause/Resume Button */}
          <button
            onClick={() => setIsStreamPaused(!isStreamPaused)}
            className={`px-3 py-1 text-xs font-bold rounded border transition-colors ${
              isStreamPaused
                ? 'bg-amber-900/50 border-amber-700 text-amber-500 hover:bg-amber-900'
                : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'
            }`}
          >
            {isStreamPaused ? 'Resume Live Inflow' : 'Pause Live Inflow'}
          </button>

          {/* Connection Indicator */}
          <div className="flex items-center space-x-2 px-3 py-1 rounded bg-slate-800 border border-slate-700">
            <Activity size={16} className={isConnected ? "text-emerald-500 animate-pulse" : "text-amber-500"} />
            <span className={`text-xs font-bold ${isConnected ? 'text-emerald-500' : 'text-amber-500'}`}>
              {isConnected ? 'STREAM CONNECTED' : 'CONNECTING...'}
            </span>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Live Request Drawer (Left Sidebar) */}
        <aside className="w-80 flex-none bg-slate-900 border-r border-slate-800 flex flex-col z-10 shadow-[4px_0_24px_rgba(0,0,0,0.5)]">
          <div className="p-4 border-b border-slate-800 bg-slate-800/50">
            <h2 className="text-sm font-bold tracking-widest text-slate-400 uppercase">Live Request Drawer</h2>
            <p className="text-xs text-slate-500 mt-1">Real-time incoming commuter pings</p>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-2">
            {[...passengerPings].reverse().map((ping, idx) => (
              <div
                key={`${ping.passenger_id}-${idx}`}
                className="p-3 bg-slate-800/80 border border-slate-700 rounded shadow-sm animate-ping-entry flex flex-col"
              >
                <div className="flex justify-between items-center mb-1">
                  <span className="text-sm font-bold text-slate-200">
                    {ping.passenger_name || `Rider #${ping.passenger_id.slice(0, 4)}`}
                  </span>
                  <span className="text-xs text-slate-400 font-mono">
                    {formatRelativeTime(ping.timestamp)}
                  </span>
                </div>
                <div className="text-xs text-slate-500 flex justify-between">
                  <span>requested drop</span>
                  <span className={ping.source === 'manual' ? 'text-blue-400 font-bold' : 'text-emerald-500'}>
                    {ping.source === 'manual' ? 'Manual Ping' : 'Auto Stream'}
                  </span>
                </div>
              </div>
            ))}
            {passengerPings.length === 0 && (
              <div className="text-center p-8 text-slate-600 text-sm italic">
                Waiting for incoming requests...
              </div>
            )}
          </div>
        </aside>

      {/* Operations Dashboard Canvas */}
      <main className="flex-1 relative">
        <MapContainer
          center={TRANSIT_HUB_COORDS}
          zoom={13}
          zoomControl={false}
          style={{ width: '100%', height: '100%', background: '#020617' }} // bg-slate-950
        >
          <MapClickHandler />
          {/* CartoDB Dark Matter tiles */}
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
          />
          <Marker position={TRANSIT_HUB_COORDS} icon={pulseIcon}>
            <Popup className="dark-popup">
              <div className="font-bold text-slate-800">Central Transit Hub</div>
              <div className="text-sm text-slate-600">Active Node</div>
            </Popup>
          </Marker>

          {/* Passenger Pings */}
          {passengerPings.map(ping => (
            <Marker
              key={ping.passenger_id}
              position={[ping.lat, ping.lng]}
              icon={passengerPingIcon}
            >
              <Popup className="dark-popup">
                <div className="font-bold text-slate-800">Passenger</div>
                <div className="text-xs text-slate-500 font-mono">ID: {ping.passenger_id.slice(0,8)}...</div>
                <div className="text-xs text-slate-600">Status: {ping.status}</div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </main>
      </div>
    </div>
  );
}

export default App;
