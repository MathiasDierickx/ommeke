"use client";
import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';
import type { ProgressEvent } from '@/lib/event-stream';
export function RouteProgress({event}:{event:ProgressEvent|null}) {
  const [seconds,setSeconds]=useState(0);
  useEffect(()=>{const start=Date.now();const timer=setInterval(()=>setSeconds(Math.floor((Date.now()-start)/1000)),1000);return()=>clearInterval(timer);},[]);
  return <section className="route-progress" aria-label="Voortgang van je route" aria-busy="true">
    <div role="status" aria-live="polite"><LoaderCircle className="spin"/><strong>{event?.message||"Verbinding maken met het routeatelier…"}</strong></div>
    <small>{seconds<60?`${seconds} sec`:`${Math.floor(seconds/60)} min ${seconds%60} sec`} bezig</small>
    <p>{seconds>60?"Dit duurt langer dan gebruikelijk. Laat dit venster open; je hoeft je vraag niet opnieuw te versturen.":"Je ziet hier de stappen die het routeatelier werkelijk uitvoert."}</p>
  </section>;
}
