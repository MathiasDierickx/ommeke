"use client";
import { useRef, useState } from "react";
import { apiRequest } from "@/lib/api";

type Result = { status: string; draft: string; conversation_id?: string; vragen?: { vraag: string; opties: Record<string, unknown> }[] };
export function QuickPlan({ token, onRoute, onConversation }: { token: string; onRoute: (id: string) => void; onConversation: (id: string) => void }) {
  const [start, setStart] = useState("");
  const [km, setKm] = useState(40);
  const [activity, setActivity] = useState("fietsen");
  const [goal, setGoal] = useState("toeren");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result>();
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const lock = useRef(false);
  function locate() {
    if (!navigator.geolocation) { setError("Locatie is niet beschikbaar. Vul je startplaats in."); return; }
    navigator.geolocation.getCurrentPosition(p => { setStart(`${p.coords.latitude.toFixed(6)},${p.coords.longitude.toFixed(6)}`); setError(""); }, () => setError("Locatie kon niet worden opgehaald. Vul je startplaats in."), { timeout: 12000, maximumAge: 60000 });
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); if (lock.current) return;
    const values = { start, target_km: km, activiteit: activity, doel: goal };
    const signature = JSON.stringify(values);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    lock.current = true; setBusy(true); setError(""); setResult(undefined);
    try {
      const next = await apiRequest<Result>("/api/routes", token, { method: "POST", body: JSON.stringify({ ...values, request_id: pending.current.id }) });
      pending.current = null;
      if (next.status === "ready") onRoute(next.draft); else setResult(next);
    } catch (e) { setError(e instanceof Error ? e.message : "Route maken mislukt."); }
    finally { lock.current = false; setBusy(false); }
  }
  return <section className="quick-plan" aria-label="Snel een route maken">
    <h2>Een lus vanaf hier</h2>
    <form onSubmit={e => void submit(e)}>
      <label>Startplaats<input required maxLength={160} value={start} onChange={e => setStart(e.target.value)} placeholder="Plaats, adres of coördinaten" /></label>
      <button type="button" onClick={locate}>Mijn locatie</button>
      <label>Afstand: {km} km<input type="range" min="1" max="150" value={km} onChange={e => setKm(Number(e.target.value))} /></label>
      <label>Activiteit<select value={activity} onChange={e => setActivity(e.target.value)}><option value="fietsen">Fietsen</option><option value="trail">Wandelen / trail</option></select></label>
      <label>Doel<select value={goal} onChange={e => setGoal(e.target.value)}><option value="toeren">Toeren</option><option value="hoogtemeters">Klimmen</option><option value="offroad">Onverhard</option><option value="kort">Kort</option></select></label>
      <button type="submit" disabled={busy}>{busy ? "Route wordt berekend…" : "Maak mijn route"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {result?.vragen?.map(q => <div key={q.vraag}><p>{q.vraag}</p>{Object.keys(q.opties).map(option => <button key={option} onClick={() => { if (result.conversation_id) { sessionStorage.setItem(`ommeke-answer:${result.conversation_id}`, `${q.vraag} Mijn keuze: ${option}. Ga verder met routeconcept ${result.draft}.`); onConversation(result.conversation_id); } }}>{option.replaceAll("_", " ")}</button>)}</div>)}
    {result?.conversation_id && <button onClick={() => onConversation(result.conversation_id!)}>Wensen aanvullen in het gesprek</button>}
  </section>;
}
