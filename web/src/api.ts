// In production the API is same-origin (Cloudflare Pages Functions serve /api/*),
// so the base is "". In Vite dev we hit the local FastAPI. Override with
// VITE_API_BASE if needed.
const fallback = import.meta.env.DEV ? "http://localhost:8077" : "";
export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? fallback;

export interface Stats {
  active_vehicles: number;
  active_listings: number;
  vin_identification_rate: number;
  median_asking_by_trim: Record<string, number>;
}

export interface Listing {
  listing_id: number;
  vehicle_id: number;
  vin: string | null;
  year: number | null;
  trim: string;
  transmission: string;
  price: number | null;
  mileage: number | null;
  source: string | null;
  url: string;
  first_seen: string;
  last_seen: string;
}

export interface HistoryPoint {
  listing_id: number;
  source_id: number;
  observed_at: string;
  price: number | null;
  mileage: number | null;
  status: string;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const getStats = () => get<Stats>("/api/stats");
export const getListings = () => get<Listing[]>("/api/listings");
export const getHistory = (vehicleId: number) =>
  get<{ vehicle_id: number; observations: HistoryPoint[] }>(
    `/api/vehicles/${vehicleId}/history`,
  );
