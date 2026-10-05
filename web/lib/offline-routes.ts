// Offline routeopslag in localStorage. Pure functies (zonder DOM) voor de begrenzing,
// dunne wrappers voor opslag. Zie ook public/offline.js, dat dezelfde sleutel leest.
export const OFFLINE_KEY = "ommeke-offline-routes-v1";
export const OFFLINE_EVENT = "ommeke-offline-changed";
/** Expliciet bewaarde routes ("Bewaar offline"). */
export const MAX_SAVED = 10;
/** Automatisch bewaarde, recent geopende routes. */
export const MAX_AUTO = 5;
/** Totale JSON-grootte; localStorage heeft meestal ~5 MB per origin. */
export const MAX_BYTES = 2_000_000;
/** Een enkele route boven deze grootte wordt automatisch niet bewaard. */
export const MAX_ROUTE_BYTES = 600_000;

export type OfflineEntry = {
  id: string;
  name: string;
  revision: number;
  geometry: { points: [number, number][]; elevation?: { km: number; ele: number }[]; climbs?: unknown[]; start?: unknown };
  saved_at: string;
  /** true = alleen automatisch bewaard; ontbreekt = expliciet bewaard. */
  auto?: boolean;
};

const size = (entries: OfflineEntry[]) => JSON.stringify(entries).length;

/** Houdt alleen wat de offline weergave nodig heeft (geen POI's e.d.). */
export function slimGeometry(geometry: OfflineEntry["geometry"]): OfflineEntry["geometry"] {
  return { points: geometry.points, elevation: geometry.elevation, climbs: geometry.climbs, start: geometry.start };
}

/**
 * Voegt een route toe en past de grenzen toe: nieuwste eerst, max MAX_SAVED
 * expliciete en MAX_AUTO automatische, en een totale bytegrens waarbij eerst de
 * oudste automatische en daarna de oudste expliciete routes sneuvelen.
 * Een expliciet bewaarde route blijft expliciet wanneer ze automatisch ververst wordt.
 */
export function upsertEntry(list: OfflineEntry[], entry: OfflineEntry, maxBytes = MAX_BYTES): OfflineEntry[] {
  const existing = list.find(r => r.id === entry.id);
  const merged: OfflineEntry = { ...entry };
  if (existing && !existing.auto) delete merged.auto;
  const next = [merged, ...list.filter(r => r.id !== entry.id)];
  const explicit = next.filter(r => !r.auto).slice(0, MAX_SAVED);
  const auto = next.filter(r => r.auto).slice(0, MAX_AUTO);
  let kept = next.filter(r => explicit.includes(r) || auto.includes(r));
  while (kept.length > 1 && size(kept) > maxBytes) {
    const reversed = [...kept].reverse();
    const victim = reversed.find(r => r.auto && r.id !== merged.id) ?? reversed.find(r => r.id !== merged.id);
    if (!victim) break;
    kept = kept.filter(r => r !== victim);
  }
  return kept;
}

export function removeEntry(list: OfflineEntry[], id: string): OfflineEntry[] {
  return list.filter(r => r.id !== id);
}

export function parseEntries(raw: string | null): OfflineEntry[] {
  try {
    const value = JSON.parse(raw || "[]");
    return Array.isArray(value) ? value.filter(r => r && typeof r.id === "string" && r.geometry?.points?.length) : [];
  } catch { return []; }
}

export function readOffline(): OfflineEntry[] {
  try { return parseEntries(localStorage.getItem(OFFLINE_KEY)); } catch { return []; }
}

function write(entries: OfflineEntry[]): boolean {
  try {
    localStorage.setItem(OFFLINE_KEY, JSON.stringify(entries));
    window.dispatchEvent(new Event(OFFLINE_EVENT));
    return true;
  } catch { return false; }
}

type RouteLike = { id: string; name: string; revision: number; geometry?: { points: [number, number][] } | null };

/** Bewaart een route; bij vol geheugen vallen oudere routes af tot het past. Geeft false als het niet lukt. */
export function storeRoute(route: RouteLike, auto: boolean): boolean {
  if (!route.geometry?.points?.length) return false;
  const entry: OfflineEntry = {
    id: route.id, name: route.name, revision: route.revision, saved_at: new Date().toISOString(),
    geometry: slimGeometry(route.geometry as OfflineEntry["geometry"]), ...(auto ? { auto: true } : {}),
  };
  if (auto && JSON.stringify(entry).length > MAX_ROUTE_BYTES) return false;
  const current = readOffline().find(r => r.id === route.id);
  if (auto && current && current.revision === route.revision && current.name === route.name) return true;
  let next = upsertEntry(readOffline(), entry);
  for (;;) {
    if (write(next)) return true;
    const drop = [...next].reverse().find(r => r.id !== route.id);
    if (!drop) return false;
    next = removeEntry(next, drop.id);
  }
}

export function clearOffline(): void {
  try { localStorage.removeItem(OFFLINE_KEY); window.dispatchEvent(new Event(OFFLINE_EVENT)); } catch { /* geen opslag */ }
}

export function registerOfflineWorker(): void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  void navigator.serviceWorker.register("/offline-sw.js").catch(() => undefined);
}
