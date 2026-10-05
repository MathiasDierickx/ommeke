import type { Route } from "./types";

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("nl-BE");
}

export type ActivityFilter = "all" | "voet" | "fiets";
const ON_FOOT = new Set(["wandelen", "trail", "wegloop"]);

/** Te voet of met de fiets; oude routes heten nog "fietsen" of "trail". */
export function activityKind(activity?: string | null): "voet" | "fiets" {
  return activity && ON_FOOT.has(activity) ? "voet" : "fiets";
}

const LABELS: Record<string, string> = {
  wandelen: "Wandelen", wegloop: "Hardlopen", trail: "Trail", stadsfiets: "Stadsfiets", toerfiets: "Toerfiets",
  koersfiets: "Racefiets", gravel: "Gravel", mtb: "Mountainbike", fietsen: "Fietsen",
};

export function activityLabel(activity?: string | null): string {
  return (activity && LABELS[activity]) || "Fietsen";
}

export function filterRoutes(routes: Route[], query: string, activity: ActivityFilter): Route[] {
  const words = normalize(query).trim().split(/\s+/).filter(Boolean);
  return routes.filter(route => {
    if (activity !== "all" && activityKind(route.activity) !== activity) return false;
    const text = normalize(`${route.name} ${route.start || ""} ${route.region || ""}`);
    return words.every(word => text.includes(word));
  });
}
