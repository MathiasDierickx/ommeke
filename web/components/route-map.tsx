"use client";

import { LoaderCircle, Map as MapIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import type { RouteGeometry } from "@/lib/types";

export function RouteMap({ geometry, loading }: { geometry?: RouteGeometry | null; loading: boolean }) {
  const elementRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!elementRef.current || !geometry?.points.length) return;
    let disposed = false;
    let cleanup = () => {};
    let readyFrame = 0;
    let sheetTimer = 0;

    void import("leaflet").then((L) => {
      if (disposed || !elementRef.current) return;
      const map = L.map(elementRef.current, { zoomControl: false, attributionControl: true });
      L.control.zoom({ position: "topright" }).addTo(map);
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
        subdomains: "abc",
      }).addTo(map);

      const points = geometry.points.map(([lat, lon]) => L.latLng(lat, lon));
      const line = L.polyline(points, { color: "#245a43", weight: 5, opacity: 0.96, lineCap: "round" }).addTo(map);
      const start = geometry.start;
      if (start) {
        L.marker([start.lat, start.lon], {
          icon: L.divIcon({ className: "map-marker-wrap", html: '<span class="map-marker map-marker-start"></span>', iconSize: [28, 28], iconAnchor: [14, 14] }),
          keyboard: true,
          title: start.label || "Start",
        }).addTo(map).bindTooltip(start.label || "Start");
      }
      geometry.climbs.forEach((climb, index) => {
        L.marker([climb.lat, climb.lon], {
          icon: L.divIcon({ className: "map-marker-wrap", html: `<span class="map-marker map-marker-climb">${index + 1}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
          keyboard: true,
          title: climb.id,
        }).addTo(map).bindTooltip(climb.id);
      });
      map.fitBounds(line.getBounds(), { padding: [42, 42], maxZoom: 15 });
      map.whenReady(() => {
        readyFrame = window.requestAnimationFrame(() => map.invalidateSize({ animate: false }));
        sheetTimer = window.setTimeout(() => map.invalidateSize({ animate: false }), 400);
      });
      cleanup = () => {
        window.cancelAnimationFrame(readyFrame);
        window.clearTimeout(sheetTimer);
        map.remove();
      };
    });

    return () => {
      disposed = true;
      cleanup();
    };
  }, [geometry]);

  if (loading) return <div className="map-state"><LoaderCircle className="spin" /> Routekaart laden…</div>;
  if (!geometry?.points.length) return <div className="map-state"><MapIcon />Nog geen kaart voor deze route</div>;
  return <div ref={elementRef} className="leaflet-map" aria-label="Kaart van de route" />;
}
