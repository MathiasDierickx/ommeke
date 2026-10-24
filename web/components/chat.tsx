"use client";

import { ArrowUp, Check, CircleUserRound, LoaderCircle, Route as RouteIcon, Send } from "lucide-react";
import { FormEvent } from "react";

import type { ChatMessage, Route, ProposalResult } from "@/lib/types";
import { messageOptions } from "@/lib/message-options";
import { routeTitle } from "@/lib/route-library";
import { RouteProposals } from "./route-proposals";
import { RouteQuestions, type AnswerRoute } from "./route-questions";
import { Logo } from "./brand";

const STARTERS = [
  "Een wandeling van 6 km langs water vanuit Gent",
  "60 km met de racefiets door de Vlaamse Ardennen",
  "Een rustige stadsfietstocht van 15 km in Antwerpen",
]

export function EmptyChat({ onStarter }: { onStarter: (prompt: string) => void }) {
  return (
    <section className="empty-chat" aria-labelledby="empty-chat-title">
      <h2 id="empty-chat-title">Vertel wat je zoekt</h2>
      <p>Typ hieronder in je eigen woorden wat je zoekt: waar je start, hoe lang, en wat de tocht goed maakt (rustig, langs water, met de kinderen, een café halverwege…). Hoe meer je vertelt, hoe gerichter Lus vraagt.</p>
      <div className="starter-list">
        {STARTERS.map((starter) => <button key={starter} onClick={() => onStarter(starter)}><span>{starter}</span><ArrowUp /></button>)}
      </div>
    </section>
  );
}

export function Message({ message, onRoute, onOption, routes = [], questionRouteIds = [], onAnswers, token, onProposalApplied, busy = false }: { token?: string; onProposalApplied?: (data: ProposalResult) => void; questionRouteIds?: string[]; onAnswers?: (id: string, answers: Parameters<AnswerRoute>[0], onProgress: Parameters<AnswerRoute>[1], klaar?: boolean) => Promise<void>; busy?: boolean; routes?: Route[]; message: ChatMessage; onRoute: (id: string) => void; onOption: (value: string) => void }) {
  const assistant = message.role === "assistant";
  const hasQuestions = routes.some(route => message.route_ids?.includes(route.id) && Boolean(route.vragen?.length));
  const hasProposals = routes.some(route => message.route_ids?.includes(route.id) && Boolean(route.voorstellen?.length));
  const options = hasQuestions || hasProposals ? [] : messageOptions(message);
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
      {assistant && onAnswers ? routes.filter(route => questionRouteIds.includes(route.id) && route.vragen?.length).map(route => <RouteQuestions key={route.id} route={route} disabled={busy} onFreeText={onOption} onAnswers={(answers, onProgress, klaar) => onAnswers(route.id, answers, onProgress, klaar)} />) : null}
      {assistant && token && onProposalApplied ? routes.filter(route => questionRouteIds.includes(route.id) && route.ready && route.voorstellen?.length).map(route => <RouteProposals key={route.id} routeId={route.id} proposals={route.voorstellen} token={token} disabled={busy} onApplied={onProposalApplied} />) : null}
      {routeId ? <div className="route-result">
        <button className="route-made" onClick={() => onRoute(routeId)}>{route?.ready ? <Check /> : <RouteIcon />}<span><strong>{route ? routeTitle(route) : "Je route"}</strong><small>{route?.ready ? `${route.total_km?.toLocaleString("nl-BE", { maximumFractionDigits: 1 }) || "—"} km · bekijk kaart en downloads` : route ? "Routeconcept · nog niet klaar om te vertrekken" : "Bekijk de route op de kaart"}</small></span><ArrowUp /></button>
        {route?.constraints?.waarschuwingen.length ? <p className="route-result-warning">Let op: {route.constraints.waarschuwingen.join(" · ")}</p> : null}
      </div> : null}
    </article>
  );
}

export function Composer({ value, onChange, onSubmit, busy, placeholder = "Vraag een route of pas iets aan…" }: { value: string; onChange: (value: string) => void; onSubmit: () => void; busy: boolean; placeholder?: string }) {
  const submit = (event: FormEvent) => { event.preventDefault(); onSubmit(); };
  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); onSubmit(); } }}
        placeholder={placeholder}
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
