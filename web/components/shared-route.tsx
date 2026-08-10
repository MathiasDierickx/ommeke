"use client";

import { ArrowRight, Bike, Footprints, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { publicApiRequest } from "@/lib/api";
import type { SharedRoute } from "@/lib/types";
import { Logo } from "./brand";
import { ElevationSparkline, QualityChips, StatGrid } from "./route-detail";
import { RouteMap } from "./route-map";

export function SharedRouteView({ token }: { token: string }) {
  const [route, setRoute] = useState<SharedRoute>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;
    publicApiRequest<{ route: SharedRoute }>(`/api/shared/${encodeURIComponent(token)}`)
      .then((data) => { if (active) setRoute(data.route); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Route laden mislukt."); });
    return () => { active = false; };
  }, [token]);

  if (error) {
    return (
      <main className="shared-empty">
        <Logo />
        <h1>Deze route is niet meer gedeeld</h1>
        <p>{error}</p>
        <a className="button button-primary" href="/">Maak je eigen route <ArrowRight /></a>
      </main>
    );
  }

  if (!route) return <div className="app-loading"><LoaderCircle className="spin" /> Gedeelde route laden…</div>;

  return (
    <main className="shared-route">
      <div className="route-map-canvas"><RouteMap geometry={route.geometry} loading={false} /></div>
      <header className="shared-topbar"><Logo /><strong>Lusmaker</strong><span>Gedeelde route</span></header>
      <aside className="route-sheet shared-sheet" aria-label="Gedeelde routedetails">
        <div className="sheet-handle" aria-hidden="true"><span /></div>
        <div className="route-title-row">
          <h1>{route.name}</h1>
          <span className="activity-tag">{route.activity === "trail" ? <Footprints /> : <Bike />}{route.activity}</span>
        </div>
        {route.region ? <p className="route-origin">Route in {route.region}</p> : null}
        <StatGrid route={route} />
        <ElevationSparkline values={route.geometry?.elevation} />
        <QualityChips route={route} />
        <a className="button button-primary shared-cta" href="/">Maak je eigen route <ArrowRight /></a>
        <p className="shared-note">Read-only gedeeld via Lusmaker</p>
      </aside>
    </main>
  );
}
