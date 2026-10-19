import type { RouteReason } from "./types";

// Gemiddelde tempo's per activiteit (km/u) en de extra minuten per 100 m stijging.
// shortcut: vaste tempo's, geen persoonlijk tempo; upgrade zodra de engine een `duur_min` meestuurt.
const PACE: Record<string, [kmh: number, minPer100m: number]> = {
  wandelen: [4.5, 10], wegloop: [10, 8], trail: [8, 10],
  stadsfiets: [15, 5], toerfiets: [20, 4], koersfiets: [27, 3], gravel: [20, 4], mtb: [14, 5], fietsen: [20, 4],
};

export function estimateMinutes(km?: number | null, ascendM?: number | null, activity?: string | null): number | null {
  if (km == null || !Number.isFinite(km) || km <= 0) return null;
  const [kmh, climbMin] = PACE[activity || ""] ?? PACE.fietsen;
  return Math.round((km / kmh) * 60 + ((ascendM || 0) / 100) * climbMin);
}

/** Afstand die in een gegeven tijd past, zonder hoogtemeters; voor de tijdankers op het startscherm. */
export function kmForMinutes(minutes: number, activity?: string | null, max = Infinity): number {
  const [kmh] = PACE[activity || ""] ?? PACE.fietsen;
  return Math.max(1, Math.min(max, Math.round((minutes / 60) * kmh)));
}

/** "45 min", "1 u 05", "2 u 30". */
export function formatDuration(minutes: number | null): string {
  if (minutes == null) return "—";
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)} u ${String(minutes % 60).padStart(2, "0")}`;
}

export type ReasonTone = "ok" | "soft" | "hard" | "unknown";

/** Vinkje, waarschuwing of kruisje: een zacht criterium dat niet haalt is een ⚠️, een hard een ❌. */
export function reasonTone(reason: Pick<RouteReason, "ok" | "hard">): ReasonTone {
  if (reason.ok === null || reason.ok === undefined) return "unknown";
  if (reason.ok) return "ok";
  return reason.hard ? "hard" : "soft";
}
