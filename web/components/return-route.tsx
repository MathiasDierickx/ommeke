"use client";
import { useRef, useState } from "react";
export function ReturnRoute({ onReturn }: { onReturn: (lat:number,lon:number,budget:number | "kortste",requestId:string)=>Promise<void> }) {
  const [budget,setBudget]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const lock=useRef(false);
  const pending=useRef<{lat:number;lon:number;budget:number | "kortste";id:string} | undefined>(undefined);
  async function submit() {
    if(lock.current)return; lock.current=true; setBusy(true);setError("");
    try {
      const value=budget==="" ? "kortste" : Number(budget);
      if(value!=="kortste" && (!Number.isFinite(value)||value<=0)) throw new Error("Geef je resterende kilometerbudget.");
      if(!pending.current || pending.current.budget!==value) {
        const p=await new Promise<GeolocationPosition>((resolve,reject)=>navigator.geolocation ? navigator.geolocation.getCurrentPosition(resolve,reject,{timeout:12000,maximumAge:30000}):reject(new Error("Locatie is niet beschikbaar.")));
        pending.current={lat:p.coords.latitude,lon:p.coords.longitude,budget:value,id:crypto.randomUUID()};
      }
      const p=pending.current; await onReturn(p.lat,p.lon,p.budget,p.id);pending.current=undefined;
    }catch(e){setError(e instanceof Error ? e.message : "Je locatie kon niet worden opgehaald. Geef locatietoestemming om terug te keren.");}
    finally{lock.current=false;setBusy(false);}
  }
  return <details><summary>Breng me terug</summary><p>Vanaf je huidige locatie terug naar de start, met dezelfde routevoorkeuren. Je route krijgt een nieuwe revisie.</p><label>Resterend budget (km, leeg voor kortste)<input type="number" min="0.1" max="300" step="0.1" value={budget} onChange={e=>setBudget(e.target.value)} /></label><button className="button" disabled={busy} onClick={()=>void submit()}>{busy?"Terugweg berekenen…":"Gebruik mijn locatie en bereken terugweg"}</button>{error&&<p role="alert">{error}</p>}</details>;
}
