"use client";

import { ArrowDownToLine, ArrowLeft, Bike, Check, Copy, Footprints, LoaderCircle, MapPin, Menu, Mountain, Pencil, Plus, Share2, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { NearbyClimb, Route, RouteAdjustment, RouteGeometry, SharedRoute } from "@/lib/types";
import { RouteQuestions } from "./route-questions";
import type { ProgressEvent } from "@/lib/event-stream";
import { activityKind, activityLabel } from "@/lib/route-library";
import { Logo } from "./brand";
import { OfflineRoute } from "./offline-route";
import { ReturnRoute } from "./return-route";
import { RouteMap } from "./route-map";

export function StatGrid({ route }: { route: Route | SharedRoute }) {
  return (
    <dl className="route-stats">
      <div><dt>Afstand</dt><dd>{route.total_km != null ? route.total_km.toLocaleString("nl-BE", { maximumFractionDigits: 1 }) : "—"}<small> km</small></dd></div>
      <div><dt>Hoogtemeters</dt><dd>{route.elevation_gain_m != null ? Math.round(route.elevation_gain_m) : "—"}<small> m</small></dd></div>
      <div><dt>Klimmen</dt><dd>{route.climbs.length}</dd></div>
    </dl>
  );
}

const CHART_WIDTH = 320;
const CHART_HEIGHT = 64;
const CHART_TOP = 5;

export function ElevationSparkline({ values }: { values?: RouteGeometry["elevation"] }) {
  const chart = useMemo(() => {
    const points = values?.filter(({ km, ele }) => Number.isFinite(km) && Number.isFinite(ele));
    if (!points || points.length < 2) return null;

    const maxKm = Math.max(...points.map(({ km }) => km));
    const minElevation = Math.min(...points.map(({ ele }) => ele));
    const maxElevation = Math.max(...points.map(({ ele }) => ele));
    if (maxKm <= 0) return null;

    const elevationRange = Math.max(1, maxElevation - minElevation);
    const line = points.map(({ km, ele }, index) => {
      const x = (Math.max(0, km) / maxKm) * CHART_WIDTH;
      const y = CHART_HEIGHT - ((ele - minElevation) / elevationRange) * (CHART_HEIGHT - CHART_TOP);
      return `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return { line, minElevation, maxElevation };
  }, [values]);
  if (!chart) return null;

  return (
    <figure className="elevation-profile" aria-label={`Hoogteprofiel van ${Math.round(chart.minElevation)} tot ${Math.round(chart.maxElevation)} meter`}>
      <figcaption>
        <span>Hoogteprofiel</span>
        <span>{Math.round(chart.minElevation)} m <span aria-hidden="true">—</span> {Math.round(chart.maxElevation)} m</span>
      </figcaption>
      <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} preserveAspectRatio="none" role="img" aria-hidden="true">
        <path className="elevation-fill" d={`${chart.line} L${CHART_WIDTH},${CHART_HEIGHT} L0,${CHART_HEIGHT} Z`} />
        <path className="elevation-line" d={chart.line} />
      </svg>
    </figure>
  );
}

export function QualityChips({ route }: { route: Route | SharedRoute }) {
  const quality = "computed" in route ? route.computed?.kwaliteit ?? route.kwaliteit : route.kwaliteit;
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
  onDownloadFit,
  onReturn,
  onRename,
  onDelete,
  onAdjust,
  onAnswers,
  onLoadClimbs,
  onShare,
  onUnshare,
  onFeedback,
  mapSlot,
  onBack,
  onMenu,
}: {
  mapSlot?: React.ReactNode;
  route: Route | null;
  loading: boolean;
  onDownload: (poiKind: string) => void;
  onDownloadFit?: (poiKind: string) => void;
  onReturn?: (lat:number,lon:number,budget:number | "kortste",requestId:string,closure?:{lat:number;lon:number})=>Promise<void>;
  onRename: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onAdjust: (adjustment: RouteAdjustment) => Promise<void>;
  onAnswers: (answers: Record<string, string>, onProgress: (event: ProgressEvent) => void) => Promise<void>;
  onLoadClimbs: () => Promise<NearbyClimb[]>;
  onShare: () => Promise<{ token: string; url: string } | undefined>;
  onBack: () => void;
  onMenu: () => void;
  onUnshare: () => Promise<void>;
  onFeedback: (category: string, comment: string) => Promise<void>;
}) {
  const [poiKind, setPoiKind] = useState("alle");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(route?.name || "");
  const [adjusting, setAdjusting] = useState(false);
  const [targetDistance, setTargetDistance] = useState("");
  const distanceStep = activityKind(route?.activity) === "voet" ? 1 : 5;
  useEffect(() => {
    setTargetDistance(String(route?.constraints?.doel_km ?? route?.total_km ?? ""));
  }, [route?.id, route?.revision, route?.constraints?.doel_km, route?.total_km]);
  const [avoidPlace, setAvoidPlace] = useState("");
  const [showClimbs, setShowClimbs] = useState(false);
  const [nearbyClimbs, setNearbyClimbs] = useState<NearbyClimb[]>([]);
  const [shareUrl, setShareUrl] = useState<string>();
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState("bruikbaar");
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackStatus, setFeedbackStatus] = useState("");
  useEffect(() => {
    setName(route?.name || "");
    setEditing(false);
    setShowClimbs(false);
    setNearbyClimbs([]);
    setShareUrl(undefined);
  }, [route?.id, route?.name]);

  const adjust = async (value: RouteAdjustment) => {
    if (adjusting) return;
    setAdjusting(true);
    try { await onAdjust(value); } finally { setAdjusting(false); }
  };

  const toggleClimbs = async () => {
    if (showClimbs) { setShowClimbs(false); return; }
    setAdjusting(true);
    try {
      setNearbyClimbs(await onLoadClimbs());
      setShowClimbs(true);
    } finally { setAdjusting(false); }
  };

  const share = async () => {
    const result = await onShare();
    if (result) setShareUrl(result.url);
  };

  return (
    <section className="route-fullscreen">
      <div className="route-map-canvas">{mapSlot ?? <RouteMap geometry={route?.geometry} loading={loading} onPoiChange={setPoiKind} />}</div>
      <header className="route-topbar">
        <button className="icon-button route-menu" onClick={onMenu} aria-label="Open navigatie"><Menu /></button>
        <div className="route-topbar-title"><Logo /><span><strong>{route?.name || "Route laden…"}</strong></span></div>
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
            <span className="activity-tag">{activityKind(route.activity) === "voet" ? <Footprints /> : <Bike />}{activityLabel(route.activity)}</span>
          </div>
          <p className="route-origin">Vertrek vanuit {route.start || route.geometry?.start?.label || "je gekozen startpunt"}</p>
          {!route.ready && route.vragen?.length ? <RouteQuestions route={route} onAnswers={onAnswers} onBusyChange={setAdjusting} disabled={adjusting} submitLabel="Maak mijn route met deze keuzes" /> : !route.ready ? <section className="route-pending" aria-labelledby="route-pending-title">
            <h3 id="route-pending-title">Deze route is nog niet berekend</h3>
            <p>Er zijn geen open vragen. Je route wordt berekend met de opgeslagen afstand.</p>
            <button className="button button-primary" disabled={adjusting || !route.constraints?.doel_km} onClick={() => void adjust({ target_km: route.constraints?.doel_km ?? undefined })}>{adjusting ? "Route wordt berekend…" : "Route berekenen"}</button>
          </section> : null}
          <StatGrid route={route} />
          <ElevationSparkline values={route.geometry?.elevation} />
          <QualityChips route={route} />
          {route.constraints && (route.constraints.doel_km != null || route.constraints.maximum_is_hard || route.constraints.waarschuwingen.length > 0) ? (
            <section className="route-constraints" aria-label="Afstand en routewensen">
              {route.constraints.doel_km != null ? <p>Streefafstand: {route.constraints.doel_km.toLocaleString("nl-BE")} km</p> : null}
              {route.constraints.maximum_is_hard && route.constraints.maximum_km != null ? <p>Hard maximum: {route.constraints.maximum_km.toLocaleString("nl-BE")} km</p> : null}
              {route.constraints.waarschuwingen.length ? <div role="status"><strong>Niet alle wensen zijn gehaald</strong><ul>{route.constraints.waarschuwingen.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div> : null}
            </section>
          ) : null}
          <div className="route-downloads">
            <button className="button button-primary" onClick={() => onDownload(poiKind)} disabled={!route.ready}><ArrowDownToLine /> Download GPX</button>
            {onDownloadFit && <button className="button button-secondary" onClick={() => onDownloadFit?.(poiKind)} disabled={!route.ready}><ArrowDownToLine /> Download FIT</button>}
          </div>
          {!route.ready ? <p className="route-download-note">Downloads zijn beschikbaar zodra de route is berekend.</p> : null}
          <div className="route-actions">
            <button className="button button-quiet" onClick={() => void share()}><Share2 /> Deel</button>
            {route.shared || shareUrl ? <button className="button button-quiet" onClick={async () => { try { await onUnshare(); setShareUrl(undefined); } catch { /* caller toont de fout; link blijft zichtbaar */ } }}>Stop delen</button> : null}
            <button className="button button-danger" onClick={() => void onDelete()} aria-label="Route verwijderen"><Trash2 /><span>Verwijder</span></button>
          </div>
          {route.ready ? <div className="route-journey"><OfflineRoute route={route} />{onReturn && <ReturnRoute onReturn={onReturn} />}</div> : null}
          {shareUrl ? (
            <div className="share-result">
              <a href={shareUrl} target="_blank" rel="noreferrer">{shareUrl}</a>
              <button className="icon-button" onClick={async () => { await navigator.clipboard.writeText(shareUrl); setCopied(true); }} aria-label="Deellink kopiëren">{copied ? <Check /> : <Copy />}</button>
              {typeof navigator.share === "function" ? <button className="icon-button" onClick={() => void navigator.share({ title: route.name, url: shareUrl })} aria-label="Deellink delen"><Share2 /></button> : null}
            </div>
          ) : null}
          <details className="account-controls"><summary>Feedback over deze route</summary>
            <form onSubmit={async event => { event.preventDefault(); setFeedbackStatus("Verzenden…"); try { await onFeedback(feedback, feedbackText); setFeedbackStatus("Bedankt, je feedback is bewaard."); setFeedbackText(""); } catch { setFeedbackStatus("Feedback bewaren mislukt. Probeer opnieuw."); } }}>
              <label>Hoe is de route?<select value={feedback} onChange={event => setFeedback(event.target.value)}><option value="bruikbaar">Bruikbaar</option><option value="verkeerde_weg">Verkeerde weg</option><option value="afstand">Afstand klopt niet</option><option value="wens_gemist">Wens gemist</option><option value="anders">Anders</option></select></label>
              <label>Toelichting (optioneel)<textarea value={feedbackText} onChange={event => setFeedbackText(event.target.value)} maxLength={1000} /></label>
              <button disabled={feedbackStatus === "Verzenden…"}>Feedback bewaren</button><p role="status">{feedbackStatus}</p>
            </form>
          </details>
          <section className="route-adjust" aria-labelledby="adjust-title">
            <div className="adjust-heading"><div><small>Routeatelier</small><h3 id="adjust-title">Aanpassen</h3></div><span role="status">{adjusting ? <><LoaderCircle className="spin" aria-hidden="true" /><span className="sr-only">Route aanpassen…</span></> : null}</span></div>
            <div className="adjust-row">
              <span>Afstand</span>
              <div className="adjust-buttons">
                <button disabled={adjusting || route.total_km == null || route.total_km <= 1} onClick={() => void adjust({ target_km: Math.max(1, (route.total_km || 0) - distanceStep) })}>−{distanceStep} km</button>
                <button disabled={adjusting || route.total_km == null} onClick={() => void adjust({ target_km: (route.total_km || 0) + distanceStep })}><Plus />{distanceStep} km</button>
              </div>
            </div>
            <form className="distance-form" onSubmit={event => {
              event.preventDefault();
              const km = Number(targetDistance);
              if (Number.isFinite(km) && km >= 1 && km <= 300) void adjust({target_km: km});
            }}>
              <label>Gewenste afstand (km)<input type="number" min="1" max="300" step="0.1" required disabled={adjusting} value={targetDistance} onChange={event => setTargetDistance(event.target.value)} /></label>
              <button disabled={adjusting || !targetDistance}>{adjusting ? "Route aanpassen…" : "Bereken opnieuw"}</button>
            </form>
            <div className="adjust-row adjust-goals">
              <span>Doel</span>
              <div className="adjust-buttons">
                <button disabled={adjusting} onClick={() => void adjust({ doel: "hm" })}><Mountain /> Klimmen</button>
                <button disabled={adjusting} onClick={() => void adjust({ doel: "offroad" })}>Offroad</button>
                <button disabled={adjusting} onClick={() => void adjust({ doel: "toeren" })}>Toeren</button>
                <button disabled={adjusting} onClick={() => void adjust({ doel: "kort" })}>Kort</button>
              </div>
            </div>
            <button className="adjust-disclosure" disabled={adjusting} onClick={() => void toggleClimbs()}><Mountain /> Klim toevoegen <span>{showClimbs ? "Sluiten" : "Bekijken"}</span></button>
            {showClimbs ? (
              <div className="nearby-climbs">
                {nearbyClimbs.length ? nearbyClimbs.map((climb) => (
                  <button key={climb.id} disabled={adjusting || route.climbs.includes(climb.id)} onClick={() => void adjust({ voeg_klimmen_toe: [climb.id] })}>
                    <span><strong>{climb.naam}</strong><small>{climb.km.toLocaleString("nl-BE", { maximumFractionDigits: 1 })} km · +{climb.hm} hm</small></span>
                    <Plus />
                  </button>
                )) : <p>Geen klimmen binnen 15 km van deze route.</p>}
              </div>
            ) : null}
            <form className="avoid-place" onSubmit={(event) => { event.preventDefault(); const value = avoidPlace.trim(); if (value) void adjust({ vermijd_plaatsen: [value] }).then(() => setAvoidPlace("")); }}>
              <MapPin />
              <input value={avoidPlace} onChange={(event) => setAvoidPlace(event.target.value)} placeholder="Plaats vermijden" aria-label="Plaats vermijden" />
              <button disabled={adjusting || !avoidPlace.trim()}>Vermijd</button>
            </form>
          </section>
        </aside>
      ) : null}
    </section>
  );
}
