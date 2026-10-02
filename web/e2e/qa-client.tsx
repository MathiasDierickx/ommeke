"use client";
import { useState } from "react";
import { RouteDetail } from "../components/route-detail";
import { Sidebar } from "../components/sidebar";
import type { Route } from "../lib/types";

const initial: Route = { id: "fixture", revision: 1, name: "Testrit langs het water", created: "2026-10-02", start: "Testplaats", activity: "fietsen", region: "vlaanderen", climbs: [], total_km: 30, elevation_gain_m: 200, ready: true, download_url: undefined };
export function QaClient() {
  const [route, setRoute] = useState(initial);
  const [event, setEvent] = useState("Klaar voor lokale controle");
  const [conflict, setConflict] = useState(false);
  const [menu, setMenu] = useState(false);
  return <main className={`route-shell ${menu ? "left-open" : ""}`}>
    <Sidebar accountSlot={<p>Accountacties worden afzonderlijk offline getest.</p>} conversations={[]} routes={[route]} session={{ accessToken: "fixture", idToken: "fixture", expiresAt: 0 }} onConversation={() => {}} onRoute={() => {}} onNew={() => setEvent("Nieuw gesprek")} onClose={() => setMenu(false)} onLogout={() => setEvent("Afmelden")} />
    <RouteDetail route={route} loading={false} mapSlot={<div style={{ height: "100%", background: "#e4ebdf", padding: "7rem 2rem" }}><strong>Lokale testkaart — geen netwerk</strong><p role="status">{event}</p><label><input type="checkbox" checked={conflict} onChange={e => setConflict(e.target.checked)} /> Simuleer revision-conflict</label></div>}
      onMenu={() => setMenu(true)} onBack={() => setEvent("Gesprekken")}
      onDownload={() => setEvent("GPX-download aangevraagd")}
      onRename={async name => setRoute(current => ({ ...current, name }))}
      onDelete={async () => setEvent("Verwijderen aangevraagd")}
      onAdjust={async values => { if (conflict) { setEvent("De route is intussen gewijzigd. Laad opnieuw."); return; } setRoute(current => ({ ...current, total_km: values.target_km ?? current.total_km, revision: current.revision + 1 })); setEvent("Route aangepast"); }}
      onLoadClimbs={async () => []}
      onShare={async () => { setRoute(current => ({ ...current, shared: true })); return { token: "fixture", url: "http://127.0.0.1:3017/qa-local" }; }}
      onUnshare={async () => { setRoute(current => ({ ...current, shared: false })); setEvent("Delen gestopt"); }}
      onFeedback={async category => setEvent(`Feedback: ${category}`)} />
  </main>;
}
