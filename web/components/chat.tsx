"use client";

import { ArrowUp, Check, CircleUserRound, LoaderCircle, Route as RouteIcon, Send } from "lucide-react";
import { FormEvent } from "react";

import type { ChatMessage, Route } from "@/lib/types";
import { Logo } from "./brand";

const STARTERS = [
  "Een wandeling van 6 km langs water vanuit Gent",
  "60 km met de racefiets door de Vlaamse Ardennen",
  "Een rustige stadsfietstocht van 15 km in Antwerpen",
]

function messageOptions(message: ChatMessage): string[] {
  if (message.role !== "assistant" || !message.content.includes("?")) return [];
  const options = message.content.split("\n").map((line) => line.match(/^\s*(?:[-•]|\d+[.)])\s+(.+)$/)?.[1]?.trim()).filter((value): value is string => Boolean(value));
  return options.length >= 2 && options.length <= 6 ? options : [];
}

export function EmptyChat({ onStarter }: { onStarter: (prompt: string) => void }) {
  return (
    <section className="empty-chat" aria-labelledby="empty-chat-title">
      <h2 id="empty-chat-title">Of beschrijf je lus zelf</h2>
      <p>Vertel waar je start, hoe ver je wilt en wat de tocht goed maakt. Ommeke stelt alleen de vragen die voor jouw route tellen.</p>
      <div className="starter-list">
        {STARTERS.map((starter) => <button key={starter} onClick={() => onStarter(starter)}><span>{starter}</span><ArrowUp /></button>)}
      </div>
    </section>
  );
}

export function Message({ message, onRoute, onOption, routes = [] }: { routes?: Route[]; message: ChatMessage; onRoute: (id: string) => void; onOption: (value: string) => void }) {
  const assistant = message.role === "assistant";
  const options = messageOptions(message);
  const routeId = message.route_ids?.at(-1);
  const route = routes.find(item => item.id === routeId);
  const formatLine = (line: string) => line.split(/(\*\*[^*]+\*\*)/g).map((part, index) => part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2,-2)}</strong> : part);
  return (
    <article className={`message ${assistant ? "message-assistant" : "message-user"}`}>
      <div className="message-author">{assistant ? <Logo /> : <CircleUserRound />}<span>{assistant ? "Lus" : "Jij"}</span></div>
      <div className="message-bubble">
        <div className="message-copy">{message.content.split("\n").map((line, index) => <p key={`${message.id}-${index}`}>{line ? formatLine(line) : "\u00a0"}</p>)}</div>
        {options.length ? <div className="option-chips" aria-label="Antwoordopties">{options.map((option) => <button key={option} onClick={() => onOption(option)}>{option}</button>)}</div> : null}
      </div>
      {routeId ? <div className="route-result">
        <button className="route-made" onClick={() => onRoute(routeId)}>{route?.ready ? <Check /> : <RouteIcon />}<span><strong>{route?.name || "Je route"}</strong><small>{route?.ready ? `${route.total_km?.toLocaleString("nl-BE", { maximumFractionDigits: 1 }) || "—"} km · bekijk kaart en downloads` : route ? "Routeconcept · nog niet klaar om te vertrekken" : "Bekijk de route op de kaart"}</small></span><ArrowUp /></button>
        {route?.constraints?.waarschuwingen.length ? <p className="route-result-warning">Let op: {route.constraints.waarschuwingen.join(" · ")}</p> : null}
      </div> : null}
    </article>
  );
}

export function Composer({ value, onChange, onSubmit, busy }: { value: string; onChange: (value: string) => void; onSubmit: () => void; busy: boolean }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onSubmit(); } }}
        placeholder="Vraag een route of pas iets aan…"
        rows={1}
        maxLength={4000}
        disabled={busy}
        aria-label="Bericht aan Lus"
      />
      <button type="submit" disabled={busy || !value.trim()} aria-label="Verstuur bericht">{busy ? <LoaderCircle className="spin" /> : <Send />}</button>
      <span className="composer-hint">Enter om te sturen · Shift + Enter voor een nieuwe regel</span>
    </form>
  );
}
