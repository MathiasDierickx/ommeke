"use client";
import { useEffect, useState } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import type { ProgressEvent } from '@/lib/event-stream';

export function RouteProgress({event, complete = false}:{event:ProgressEvent|null; complete?:boolean}) {
  const [seconds,setSeconds]=useState(0);
  useEffect(()=>{
    if (complete) return;
    const start=Date.now();
    const timer=setInterval(()=>setSeconds(Math.floor((Date.now()-start)/1000)),1000);
    return()=>clearInterval(timer);
  },[complete]);
  const elapsed=seconds<60?`${seconds} sec`:`${Math.floor(seconds/60)} min ${seconds%60} sec`;
  return <section className={`route-progress${complete ? ' route-progress-complete' : ''}`} aria-label="Voortgang van je opdracht" aria-busy={!complete}>
    <div role="status" aria-live="polite" aria-atomic="true">
      {complete ? <Check aria-hidden="true"/> : <LoaderCircle className="spin" aria-hidden="true"/>}
      <strong>{complete ? 'Antwoord klaar' : event?.message||'Verbinding maken met het routeatelier…'}</strong>
    </div>
    <small>{complete ? `Afgerond in ${elapsed}` : `${elapsed} bezig`}</small>
    {!complete && <p>{seconds>=60?'Een route vergelijken kan enkele minuten duren. Je hoeft je vraag niet opnieuw te versturen.':'Je ziet hier welke stap wordt uitgevoerd.'}</p>}
  </section>;
}
