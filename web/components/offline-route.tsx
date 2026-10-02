"use client";
import { useEffect, useState } from "react";
import type { Route } from "@/lib/types";
export const OFFLINE_KEY = "ommeke-offline-routes-v1";
export function OfflineRoute({route}:{route:Route}) {
  const [status,setStatus]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{setStatus("");try{const saved=JSON.parse(localStorage.getItem(OFFLINE_KEY)||"[]").find((r:Route)=>r.id===route.id);if(saved)setStatus(saved.revision===route.revision?"Deze revisie is offline bewaard.":"Een oudere revisie is offline bewaard. Bewaar opnieuw om bij te werken.");}catch{/* Storage is optional. */}},[route.id,route.revision]);
  async function save() {
    setBusy(true);
    try {
      if(!route.geometry?.points.length)throw new Error("Wacht tot de route geladen is.");
      if(!('serviceWorker' in navigator))throw new Error("Deze browser ondersteunt offline bewaren niet.");
      await navigator.serviceWorker.register('/offline-sw.js');
      await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error("Offline voorbereiding duurt te lang. Probeer opnieuw.")),20000))]);
      const previous=JSON.parse(localStorage.getItem(OFFLINE_KEY)||"[]") as Route[];
      const saved={id:route.id,name:route.name,revision:route.revision,geometry:route.geometry,saved_at:new Date().toISOString()};
      localStorage.setItem(OFFLINE_KEY,JSON.stringify([saved,...previous.filter(r=>r.id!==route.id)].slice(0,10)));
      setStatus("Deze revisie is offline bewaard. De 10 laatst bewaarde routes blijven op dit toestel, tot je afmeldt.");
    } catch(e) {setStatus(e instanceof Error?e.message:"Offline bewaren mislukt. Controleer de beschikbare opslagruimte.");}
    finally {setBusy(false);}
  }
  return <section aria-label="Offline route"><button className="button" disabled={busy||!route.geometry} onClick={()=>void save()}>{busy?"Offline voorbereiden…":"Bewaar offline"}</button><a href="/offline.html">Offline routes openen</a><p role="status">{status}</p><small>Routelijn, positie en hoogteprofiel; zonder achtergrondkaart.</small></section>;
}
