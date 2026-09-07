import { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
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
const TRANSIT_HUB_COORDS: [number, number] = [12.9784, 77.6408];

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [activePassengers, setActivePassengers] = useState(0);
  const [fleetCounters, setFleetCounters] = useState(0);
  const [time, setTime] = useState({ local: '', utc: '' });
  const wsRef = useRef<WebSocket | null>(null);

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

          {/* Connection Indicator */}
          <div className="flex items-center space-x-2 px-3 py-1 rounded bg-slate-800 border border-slate-700">
            <Activity size={16} className={isConnected ? "text-emerald-500 animate-pulse" : "text-amber-500"} />
            <span className={`text-xs font-bold ${isConnected ? 'text-emerald-500' : 'text-amber-500'}`}>
              {isConnected ? 'STREAM CONNECTED' : 'CONNECTING...'}
            </span>
          </div>
        </div>
      </header>

      {/* Operations Dashboard Canvas */}
      <main className="flex-1 relative">
        <MapContainer
          center={TRANSIT_HUB_COORDS}
          zoom={13}
          zoomControl={false}
          style={{ width: '100%', height: '100%', background: '#020617' }} // bg-slate-950
        >
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
        </MapContainer>
      </main>
    </div>
  );
}

export default App;
