"use client";

import { ArrowUp, Check, CircleUserRound, LoaderCircle, Route as RouteIcon, Send } from "lucide-react";
import { FormEvent } from "react";

import type { ChatMessage } from "@/lib/types";
import { Logo } from "./brand";

const STARTERS = [
  "Een rustige fietsroute van 50 km vanuit Wetteren",
  "35 km met zoveel mogelijk hoogtemeters",
  "Een traillus van 12 km zonder drukke wegen",
];

function messageOptions(message: ChatMessage): string[] {
  if (message.role !== "assistant" || !message.content.includes("?")) return [];
  const options = message.content.split("\n").map((line) => line.match(/^\s*(?:[-•]|\d+[.)])\s+(.+)$/)?.[1]?.trim()).filter((value): value is string => Boolean(value));
  return options.length >= 2 && options.length <= 6 ? options : [];
}

export function EmptyChat({ onStarter }: { onStarter: (prompt: string) => void }) {
  return (
    <div className="empty-chat">
      <div className="route-orbit" aria-hidden="true"><span className="orbit-dot" /><RouteIcon /></div>
      <p className="eyebrow">Nieuwe route</p>
      <h2>Waar wil je vandaag rijden?</h2>
      <p>Noem je start, afstand en wat de rit goed moet maken.</p>
      <div className="starter-list">
        {STARTERS.map((starter) => <button key={starter} onClick={() => onStarter(starter)}><span>{starter}</span><ArrowUp /></button>)}
      </div>
    </div>
  );
}

export function Message({ message, onRoute, onOption }: { message: ChatMessage; onRoute: (id: string) => void; onOption: (value: string) => void }) {
  const assistant = message.role === "assistant";
  const options = messageOptions(message);
  return (
    <article className={`message ${assistant ? "message-assistant" : "message-user"}`}>
      <div className="message-author">{assistant ? <Logo /> : <CircleUserRound />}<span>{assistant ? "Lus" : "Jij"}</span></div>
      <div className="message-bubble">
        <div className="message-copy">{message.content.split("\n").map((line, index) => <p key={`${message.id}-${index}`}>{line || "\u00a0"}</p>)}</div>
        {options.length ? <div className="option-chips" aria-label="Antwoordopties">{options.map((option) => <button key={option} onClick={() => onOption(option)}>{option}</button>)}</div> : null}
      </div>
      {message.route_ids?.length ? <button className="route-made" onClick={() => onRoute(message.route_ids!.at(-1)!)}><Check /> Route opgeslagen · open kaart <ArrowUp /></button> : null}
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
