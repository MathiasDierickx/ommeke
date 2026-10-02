import type { Route } from "./types";

function normalize(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("nl-BE");
}

export function filterRoutes(routes: Route[], query: string, activity: "all" | "fietsen" | "trail"): Route[] {
  const words = normalize(query).trim().split(/\s+/).filter(Boolean);
  return routes.filter(route => {
    if (activity !== "all" && route.activity !== activity) return false;
    const text = normalize(`${route.name} ${route.start || ""} ${route.region || ""}`);
    return words.every(word => text.includes(word));
  });
}
