"use client";
import { Bike, Footprints, LocateFixed, Minus, Plus } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { RouteProgress } from "./route-progress";
import { StreamFailure, type ProgressEvent } from "@/lib/event-stream";
import { apiStream } from "@/lib/api";
import { isOutOfCoverage } from "@/lib/interaction";

type Result = { km?: number; constraints?: { voldaan?: boolean | null; waarschuwingen: string[] }; status: string; draft: string; conversation_id?: string; vragen?: { vraag: string; opties: Record<string, unknown> }[] };
type Activity = { value: string; label: string; verb: string; km: number; max: number };

// Waarden volgen lusmaker/activities.py; afstanden zijn een redelijke start per activiteit.
const ACTIVITY_GROUPS: { name: string; icon: typeof Bike; items: Activity[] }[] = [
  { name: "Te voet", icon: Footprints, items: [
    { value: "wandelen", label: "Wandelen", verb: "wandelen", km: 6, max: 40 },
    { value: "wegloop", label: "Hardlopen", verb: "lopen", km: 10, max: 50 },
    { value: "trail", label: "Trail", verb: "lopen", km: 12, max: 60 },
  ] },
  { name: "Fiets", icon: Bike, items: [
    { value: "stadsfiets", label: "Stadsfiets", verb: "fietsen", km: 15, max: 80 },
    { value: "toerfiets", label: "Toerfiets", verb: "fietsen", km: 40, max: 150 },
    { value: "koersfiets", label: "Racefiets", verb: "koersen", km: 60, max: 200 },
    { value: "gravel", label: "Gravel", verb: "fietsen", km: 40, max: 150 },
    { value: "mtb", label: "Mountainbike", verb: "biken", km: 30, max: 100 },
  ] },
];
const ACTIVITIES = ACTIVITY_GROUPS.flatMap(group => group.items);
const GOALS = [
  { value: "toeren", label: "Ontspannen" },
  { value: "hoogtemeters", label: "Heuvels" },
  { value: "offroad", label: "Onverhard" },
];

export function QuickPlan({ token, onRoute, onConversation, onBusyChange, onResultChange }: { onResultChange?: (hasResult:boolean)=>void; onBusyChange?: (busy:boolean)=>void; token: string; onRoute: (id: string) => void; onConversation: (id: string) => void }) {
  const [start, setStart] = useState("");
  const [activity, setActivity] = useState("wandelen");
  const current = ACTIVITIES.find(item => item.value === activity) ?? ACTIVITIES[0];
  const [km, setKm] = useState(current.km);
  const kmTouched = useRef(false);
  const [goal, setGoal] = useState("toeren");
  const [locating, setLocating] = useState(false);
  const [progress,setProgress]=useState<ProgressEvent|null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [canRestart,setCanRestart]=useState(false);
  const [outside, setOutside] = useState(false);
  const [result, setResult] = useState<Result>();
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const startId = useId();
  const distanceId = useId();
  useEffect(() => { if (result) resultHeading.current?.focus(); }, [result]);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const lock = useRef(false);

  function chooseActivity(next: Activity) {
    setActivity(next.value);
    // Een wandeling van 40 km is zelden bedoeld: volg de activiteit tot de gebruiker zelf kiest.
    if (!kmTouched.current) setKm(next.km);
    else setKm(value => Math.min(value, next.max));
  }
  function changeKm(value: number) {
    kmTouched.current = true;
    setKm(Math.max(1, Math.min(current.max, Math.round(value))));
  }
  function locate() {
    if (!navigator.geolocation) { setError("Locatie is niet beschikbaar. Vul je startplaats in."); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      p => { setStart(`${p.coords.latitude.toFixed(6)},${p.coords.longitude.toFixed(6)}`); setError(""); setLocating(false); },
      () => { setError("Locatie kon niet worden opgehaald. Vul je startplaats in."); setLocating(false); },
      { timeout: 12000, maximumAge: 60000 },
    );
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); if (lock.current) return;
    const values = { start, target_km: km, activiteit: activity, doel: goal };
    const signature = JSON.stringify(values);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    lock.current = true; onBusyChange?.(true); setCanRestart(false); setProgress(null); setBusy(true); setError(""); setOutside(false); setResult(undefined); onResultChange?.(false);
    try {
      const next = await apiStream<Result>("/api/routes/stream", token, { ...values, request_id: pending.current.id }, setProgress);
      pending.current = null;
      setResult(next);
      onResultChange?.(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Route maken mislukt.");
      const isOutside = isOutOfCoverage(e);
      setOutside(isOutside);
      // Buiten het gedekte gebied is geen onderbroken poging: de invoer blijft bewerkbaar en een nieuwe start krijgt een nieuw verzoeknummer.
      if (isOutside) pending.current = null;
      setCanRestart(e instanceof StreamFailure && !isOutside);
    }
    finally { lock.current = false; setBusy(false); onBusyChange?.(false); }
  }

  const coordinates = /^-?\d+(\.\d+)?,\s*-?\d+(\.\d+)?$/.test(start.trim());
  return <section className="planner" aria-labelledby="planner-title">
    <h2 id="planner-title" className="planner-title">Waar wil je {current.verb}?</h2>
    <form hidden={result?.status === "ready"} onSubmit={e => void submit(e)}>
      <fieldset disabled={busy}>
        <legend className="sr-only">Je lus</legend>
        <div className="activity-picker">
          {ACTIVITY_GROUPS.map(group => <div className="activity-group" role="radiogroup" aria-label={`Activiteit ${group.name.toLowerCase()}`} key={group.name}>
            <span className="activity-group-name" aria-hidden="true"><group.icon />{group.name}</span>
            <div className="activity-options">
              {group.items.map(item => <label key={item.value} className="choice-chip">
                <input type="radio" name="activiteit" value={item.value} checked={activity === item.value} onChange={() => chooseActivity(item)} />
                <span>{item.label}</span>
              </label>)}
            </div>
          </div>)}
        </div>

        <div className="planner-card">
          <div className="planner-field">
            <label htmlFor={startId}>Startplaats</label>
            <div className="start-input">
              <input id={startId} required maxLength={160} value={start} onChange={e => setStart(e.target.value)} placeholder="Plaats, adres of coördinaten" autoComplete="off" />
              <button type="button" className="locate-button" onClick={locate} disabled={locating}><LocateFixed /><span>{locating ? "Zoeken…" : "Mijn locatie"}</span></button>
            </div>
            {coordinates ? <small className="field-hint">Je huidige locatie. De route krijgt de naam van de dichtste plaats.</small> : null}
          </div>

          <div className="planner-field">
            <label htmlFor={distanceId}>Afstand</label>
            <div className="distance-control">
              <button type="button" className="step-button" onClick={() => changeKm(km - 1)} aria-label="1 km korter"><Minus /></button>
              <output htmlFor={distanceId} aria-live="polite"><strong>{km}</strong> km</output>
              <button type="button" className="step-button" onClick={() => changeKm(km + 1)} aria-label="1 km langer"><Plus /></button>
              <input id={distanceId} type="range" min="1" max={current.max} value={km} onChange={e => changeKm(Number(e.target.value))} aria-valuetext={`${km} kilometer`} />
            </div>
          </div>

          <div className="planner-field" role="radiogroup" aria-label="Wat telt het meest">
            <span className="field-label" aria-hidden="true">Wat telt het meest</span>
            <div className="goal-options">
              {GOALS.map(item => <label key={item.value} className="choice-chip choice-chip-quiet">
                <input type="radio" name="doel" value={item.value} checked={goal === item.value} onChange={() => setGoal(item.value)} />
                <span>{item.label}</span>
              </label>)}
            </div>
          </div>

          <button type="submit" className="planner-submit" disabled={busy}>{busy ? "Route wordt berekend…" : "Maak mijn route"}</button>
        </div>
      </fieldset>
    </form>
    {busy && <RouteProgress event={progress} />}
    {result?.status === "ready" && <div className="quick-result">
      <h3 role="status" tabIndex={-1} ref={resultHeading}>{result.constraints?.voldaan === false ? "Route gevonden — controleer je wensen" : "Je route is klaar"}</h3>
      <p>{typeof result.km === "number" ? `${result.km.toLocaleString("nl-BE", { maximumFractionDigits: 1 })} km. ` : ""}Bekijk de kaart en download je GPX of FIT.</p>
      {result.constraints?.waarschuwingen.map(warning => <p className="route-result-warning" key={warning}>{warning}</p>)}
      <div className="quick-result-actions">
        <button className="planner-submit" onClick={() => onRoute(result.draft)}>Bekijk mijn route</button>
        <button className="quick-plan-again" onClick={() => { setResult(undefined); onResultChange?.(false); }}>Andere route plannen</button>
      </div>
    </div>}
    {result && result.status !== "ready" && <h3 className="planner-followup" role="status" tabIndex={-1} ref={resultHeading}>Nog even je wensen aanvullen</h3>}
    {error && <p role="alert" className={outside ? "planner-error quick-plan-outside" : "planner-error"}>{error}{outside ? " Pas je startplaats aan en probeer opnieuw." : ""}</p>}
    {canRestart && <button className="quick-plan-again" onClick={()=>{pending.current=null;setCanRestart(false);setError("De vorige poging is gestopt. Controleer Mijn routes: er kan al een concept bestaan. Met Maak mijn route start je bewust een nieuwe poging.");}}>Nieuwe poging voorbereiden</button>}
    {result?.vragen?.map(q => <div className="planner-question" key={q.vraag}><p>{q.vraag}</p><div className="goal-options">{Object.keys(q.opties).map(option => <button key={option} className="option-button" onClick={() => { if (result.conversation_id) { try { sessionStorage.setItem(`ommeke-answer:${result.conversation_id}`, `${q.vraag} Mijn keuze: ${option}. Ga verder met routeconcept ${result.draft}.`); } catch { /* Antwoord kan in het gesprek worden ingevuld. */ } onConversation(result.conversation_id); } }}>{option.replaceAll("_", " ")}</button>)}</div></div>)}
    {result?.conversation_id && <button className="quick-plan-again" onClick={() => onConversation(result.conversation_id!)}>Wensen aanvullen in het gesprek</button>}
  </section>;
}
