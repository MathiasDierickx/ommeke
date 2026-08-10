"use client";

import { ArrowDownToLine, ArrowLeft, Bike, Check, Footprints, Menu, Pencil, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { Route } from "@/lib/types";
import { Logo } from "./brand";
import { RouteMap } from "./route-map";

function StatGrid({ route }: { route: Route }) {
  return (
    <dl className="route-stats">
      <div><dt>Afstand</dt><dd>{route.total_km != null ? route.total_km.toFixed(1) : "—"}<small> km</small></dd></div>
      <div><dt>Hoogtemeters</dt><dd>{route.elevation_gain_m != null ? Math.round(route.elevation_gain_m) : "—"}<small> m</small></dd></div>
      <div><dt>Klimmen</dt><dd>{route.climbs.length}</dd></div>
    </dl>
  );
}

function ElevationSparkline({ values }: { values?: number[] }) {
  const path = useMemo(() => {
    if (!values || values.length < 2) return null;
    const min = Math.min(...values);
    const range = Math.max(1, Math.max(...values) - min);
    return values.map((value, index) => {
      const x = (index / (values.length - 1)) * 320;
      const y = 54 - ((value - min) / range) * 46;
      return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  }, [values]);
  if (!path) return null;
  return (
    <div className="elevation-profile" aria-label="Hoogteprofiel">
      <span>Hoogteprofiel</span>
      <svg viewBox="0 0 320 60" preserveAspectRatio="none" role="img">
        <path className="elevation-fill" d={`${path} L320,60 L0,60 Z`} />
        <path className="elevation-line" d={path} />
      </svg>
    </div>
  );
}

function QualityChips({ route }: { route: Route }) {
  const quality = route.computed?.kwaliteit;
  const chips = [
    quality?.kassei_m != null ? `${Math.round(quality.kassei_m)} m kassei` : null,
    quality?.offroad_pct != null ? `${Math.round(quality.offroad_pct)}% offroad` : null,
    quality?.populair_pct != null ? `${Math.round(quality.populair_pct)}% populair` : null,
  ].filter((value): value is string => Boolean(value));
  if (!chips.length) return null;
  return <div className="quality-chips" aria-label="Routekwaliteit">{chips.map((chip) => <span key={chip}>{chip}</span>)}</div>;
}

export function RouteDetail({
  route,
  loading,
  onDownload,
  onRename,
  onDelete,
  onBack,
  onMenu,
}: {
  route: Route | null;
  loading: boolean;
  onDownload: () => void;
  onRename: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onBack: () => void;
  onMenu: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(route?.name || "");
  useEffect(() => {
    setName(route?.name || "");
    setEditing(false);
  }, [route?.id, route?.name]);

  return (
    <section className="route-fullscreen">
      <div className="route-map-canvas"><RouteMap geometry={route?.geometry} loading={loading} /></div>
      <header className="route-topbar">
        <button className="icon-button route-menu" onClick={onMenu} aria-label="Open navigatie"><Menu /></button>
        <div className="route-topbar-title"><Logo /><span><small>Routedetail</small><strong>{route?.name || "Route laden…"}</strong></span></div>
        <button className="route-back" onClick={onBack}><ArrowLeft /> Gesprekken</button>
      </header>
      {route ? (
        <aside className="route-sheet" aria-label="Routedetails">
          <div className="sheet-handle" aria-hidden="true"><span /></div>
          <div className="route-title-row">
            {editing ? (
              <form onSubmit={async (event) => { event.preventDefault(); await onRename(name); setEditing(false); }}>
                <input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} autoFocus aria-label="Routenaam" />
                <button aria-label="Naam bewaren"><Check /></button>
              </form>
            ) : (
              <><h2>{route.name}</h2><button className="icon-button" onClick={() => setEditing(true)} aria-label="Naam wijzigen"><Pencil /></button></>
            )}
            <span className="activity-tag">{route.activity === "trail" ? <Footprints /> : <Bike />}{route.activity}</span>
          </div>
          <p className="route-origin">Vertrek vanuit {route.start || route.geometry?.start?.label || "je gekozen startpunt"}</p>
          <StatGrid route={route} />
          <ElevationSparkline values={route.geometry?.elevation} />
          <QualityChips route={route} />
          <div className="route-actions">
            <button className="button button-primary" onClick={onDownload} disabled={!route.ready}><ArrowDownToLine /> Download GPX</button>
            <button className="button button-danger" onClick={() => void onDelete()} aria-label="Route verwijderen"><Trash2 /><span>Verwijder</span></button>
          </div>
        </aside>
      ) : null}
    </section>
  );
}
