import { useEffect, useState } from "react";
import {
  getHistory,
  getListings,
  getStats,
  type HistoryPoint,
  type Listing,
  type Stats,
} from "./api";

const money = (n: number | null) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const trimLabel = (t: string) =>
  ({ cayman_gts: "GTS", cayman_s: "S", cayman: "Base" })[t] ?? t;

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-neutral-50">{value}</div>
    </div>
  );
}

function Sparkline({ points }: { points: HistoryPoint[] }) {
  const prices = points.map((p) => p.price).filter((p): p is number => p != null);
  if (prices.length < 2) return <span className="text-neutral-500">not enough history</span>;
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const w = 220;
  const h = 44;
  const span = max - min || 1;
  const d = prices
    .map((p, i) => {
      const x = (i / (prices.length - 1)) * w;
      const y = h - ((p - min) / span) * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const down = prices[prices.length - 1] < prices[0];
  return (
    <svg width={w} height={h} className="overflow-visible">
      <path d={d} fill="none" stroke={down ? "#4ade80" : "#f87171"} strokeWidth={2} />
    </svg>
  );
}

function Detail({ vehicleId, onClose }: { vehicleId: number; onClose: () => void }) {
  const [pts, setPts] = useState<HistoryPoint[] | null>(null);
  useEffect(() => {
    getHistory(vehicleId).then((r) => setPts(r.observations));
  }, [vehicleId]);
  return (
    <div className="fixed inset-0 z-10 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="h-full w-full max-w-md overflow-y-auto border-l border-neutral-800 bg-neutral-950 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Vehicle #{vehicleId} — price history</h2>
          <button onClick={onClose} className="text-neutral-400 hover:text-neutral-100">✕</button>
        </div>
        {pts == null ? (
          <p className="mt-6 text-neutral-400">Loading…</p>
        ) : (
          <>
            <div className="mt-4"><Sparkline points={pts} /></div>
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-neutral-400">
                <tr><th className="py-1">Date</th><th>Price</th><th>Miles</th><th>Src</th></tr>
              </thead>
              <tbody>
                {pts.map((p, i) => (
                  <tr key={i} className="border-t border-neutral-900">
                    <td className="py-1">{p.observed_at.slice(0, 10)}</td>
                    <td>{money(p.price)}</td>
                    <td>{p.mileage?.toLocaleString() ?? "—"}</td>
                    <td>{p.source_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [listings, setListings] = useState<Listing[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([getStats(), getListings()])
      .then(([s, l]) => {
        setStats(s);
        setListings(l);
      })
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold">981 Cayman Market Tracker</h1>
          <p className="text-sm text-neutral-400">2014–2016 Cayman S · 2015–2016 Cayman GTS</p>
        </header>

        {error && (
          <div className="mb-6 rounded-lg border border-red-900 bg-red-950/50 p-3 text-sm text-red-300">
            Could not reach API at build-time base. Is the backend running? ({error})
          </div>
        )}

        <section className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card label="Active vehicles" value={stats ? String(stats.active_vehicles) : "—"} />
          <Card label="Active listings" value={stats ? String(stats.active_listings) : "—"} />
          <Card
            label="VIN identified"
            value={stats ? `${Math.round(stats.vin_identification_rate * 100)}%` : "—"}
          />
          <Card
            label="Median S / GTS"
            value={
              stats
                ? `${money(stats.median_asking_by_trim.cayman_s ?? null)} / ${money(
                    stats.median_asking_by_trim.cayman_gts ?? null,
                  )}`
                : "—"
            }
          />
        </section>

        <section className="overflow-x-auto rounded-xl border border-neutral-800">
          <table className="w-full text-sm">
            <thead className="bg-neutral-900 text-left text-neutral-400">
              <tr>
                {["Year", "Trim", "Trans", "Price", "Miles", "Source", "VIN", ""].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {listings.map((l) => (
                <tr key={l.listing_id} className="border-t border-neutral-900 hover:bg-neutral-900/40">
                  <td className="px-3 py-2">{l.year}</td>
                  <td className="px-3 py-2 font-medium">{trimLabel(l.trim)}</td>
                  <td className="px-3 py-2 uppercase text-neutral-300">{l.transmission}</td>
                  <td className="px-3 py-2">{money(l.price)}</td>
                  <td className="px-3 py-2">{l.mileage?.toLocaleString() ?? "—"}</td>
                  <td className="px-3 py-2 text-neutral-400">{l.source}</td>
                  <td className="px-3 py-2 font-mono text-xs text-neutral-500">{l.vin ?? "—"}</td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setSelected(l.vehicle_id)}
                      className="rounded-md bg-neutral-800 px-2 py-1 text-xs hover:bg-neutral-700"
                    >
                      history
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      {selected != null && <Detail vehicleId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
