"use client";
import { useEffect, useState } from "react";
import type { Route } from "@/lib/types";
import { MAX_SAVED, OFFLINE_EVENT, readOffline, storeRoute } from "@/lib/offline-routes";
export { OFFLINE_KEY } from "@/lib/offline-routes";
export function OfflineRoute({route}:{route:Route}) {
  const [status,setStatus]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    const refresh=()=>{const saved=readOffline().find(r=>r.id===route.id);setStatus(!saved?"":saved.revision!==route.revision?"Een oudere revisie is offline bewaard. Bewaar opnieuw om bij te werken.":saved.auto?"Deze revisie is automatisch offline beschikbaar. Bewaar offline om ze vast te houden.":"Deze revisie is offline bewaard.");};
    refresh();
    window.addEventListener(OFFLINE_EVENT,refresh);
    return ()=>window.removeEventListener(OFFLINE_EVENT,refresh);
  },[route.id,route.revision]);
  async function save() {
    setBusy(true);
    try {
      if(!route.geometry?.points.length)throw new Error("Wacht tot de route geladen is.");
      if(!('serviceWorker' in navigator))throw new Error("Deze browser ondersteunt offline bewaren niet.");
      await navigator.serviceWorker.register('/offline-sw.js');
      await Promise.race([navigator.serviceWorker.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error("Offline voorbereiding duurt te lang. Probeer opnieuw.")),20000))]);
      if(!storeRoute(route,false))throw new Error("Offline bewaren mislukt. Controleer de beschikbare opslagruimte.");
      setStatus(`Deze revisie is offline bewaard. De ${MAX_SAVED} laatst bewaarde routes blijven op dit toestel, tot je afmeldt.`);
    } catch(e) {setStatus(e instanceof Error?e.message:"Offline bewaren mislukt. Controleer de beschikbare opslagruimte.");}
    finally {setBusy(false);}
  }
  return <section aria-label="Offline route"><button className="button" disabled={busy||!route.geometry} onClick={()=>void save()}>{busy?"Offline voorbereiden…":"Bewaar offline"}</button><a href="/offline.html">Offline routes openen</a><p role="status">{status}</p><small>Routelijn, positie en hoogteprofiel; zonder achtergrondkaart.</small></section>;
}
