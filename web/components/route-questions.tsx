"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "@/lib/types";
import { optionLabel, questionTopic, reasonAddsInfo, reasonText, type RouteQuestion } from "@/lib/question-labels";
import type { ProgressEvent } from "@/lib/event-stream";
import { RouteProgress } from "./route-progress";

/** `klaar`: "Maak 'm maar" — gegeven antwoorden toepassen en routeren zonder nieuwe vragen. */
export type AnswerRoute = (answers: Record<string, string>, onProgress: (event: ProgressEvent) => void, klaar?: boolean) => Promise<void>;
type QuestionRoute = Pick<Route, "id" | "vragen"> & { revision?: number };

const key = (question: RouteQuestion) => question.id || question.vraag;

/**
 * Vraagkaart: één vraag tegelijk ("1 van 3"), reden in één zin, antwoorden als
 * knoppen, "Maakt me niet uit" en "Maak 'm maar". Na de laatste vraag een
 * overzicht om na te kijken voor het versturen.
 */
export function RouteQuestions({ route, onAnswers, onFreeText, disabled = false, submitLabel = "Route berekenen", onBusyChange }: { onBusyChange?: (busy: boolean) => void; route: QuestionRoute; onAnswers: AnswerRoute; onFreeText?: (text: string) => void; disabled?: boolean; submitLabel?: string }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [index, setIndex] = useState(0);
  const [adjusting, setAdjusting] = useState(false);
  const [answerProgress, setAnswerProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState<string>();
  const lock = useRef(false);
  const questions = JSON.stringify(route.vragen);
  useEffect(() => { setAnswers({}); setIndex(0); setAnswerProgress(null); setError(undefined); }, [route.id, route.revision, questions]);
  const list = route.vragen ?? [];
  if (!list.length) return null;
  const current = list[Math.min(index, list.length)];
  const done = index >= list.length;
  // De startplaats is geen voorkeur: zonder keuze kan de engine niet verder.
  const mustAnswer = list.some(question => question.id === "startplaats" && !answers[key(question)]);

  const submit = async (chosen: Record<string, string>, klaar = false) => {
    if (disabled || lock.current) return;
    lock.current = true; setError(undefined);
    setAdjusting(true); onBusyChange?.(true); setAnswerProgress(null);
    try { await onAnswers(chosen, setAnswerProgress, klaar); setAnswers({}); setIndex(0); }
    catch (cause) { setAnswerProgress(null); setError(cause instanceof Error ? cause.message : "Route berekenen mislukt. Probeer opnieuw."); }
    finally { lock.current = false; setAdjusting(false); onBusyChange?.(false); }
  };
  const choose = (option: string) => {
    setAnswers(previous => ({ ...previous, [key(current)]: option }));
    setIndex(index + 1);
  };
  const busy = disabled || adjusting;
  const options = Object.keys(current?.opties ?? {}).filter(option => option !== "ok");

  return <section className="question-card" aria-label={done ? "Je keuzes" : current.vraag} role="group">
    {done ? <>
      <p className="question-step">Klaar</p>
      <h3>Je keuzes</h3>
      <ul className="question-summary">{list.map((question, at) => <li key={key(question)}><button type="button" disabled={busy} onClick={() => setIndex(at)} aria-label={`${question.vraag}: ${answers[key(question)] ? optionLabel(question, answers[key(question)]) : "nog geen antwoord"}, wijzigen`}>{questionTopic(question) ? <small>{questionTopic(question)}</small> : null}{answers[key(question)] ? optionLabel(question, answers[key(question)]) : "Nog geen antwoord"}</button></li>)}</ul>
      <button className="button button-primary" disabled={busy || mustAnswer} onClick={() => void submit(answers)}>{adjusting ? "Route wordt berekend…" : submitLabel}</button>
    </> : <>
      <p className="question-step">Vraag {index + 1} van {list.length}</p>
      <h3>{current.vraag}</h3>
      {reasonAddsInfo(current) ? <p className="question-reason">{reasonText(current.reden)}</p> : null}
      <ol className="question-options">{options.map((option, at) => <li key={option}><button type="button" className="question-option" disabled={busy} aria-pressed={answers[key(current)] === option} onClick={() => choose(option)}><span className="question-number" aria-hidden="true">{at + 1}</span>{optionLabel(current, option)}</button></li>)}</ol>
      {onFreeText ? <form className="question-note" onSubmit={event => { event.preventDefault(); const text = note.trim(); if (text) { onFreeText(text); setNote(""); } }}>
        <input value={note} onChange={event => setNote(event.target.value)} maxLength={500} disabled={busy} placeholder="of typ je eigen antwoord…" aria-label="Eigen antwoord" />
        <button type="submit" disabled={busy || !note.trim()}>Stuur</button>
      </form> : null}
      <div className="question-actions">
        {"ok" in (current.opties ?? {}) ? <button type="button" className="button button-quiet" disabled={busy} onClick={() => choose("ok")}>Maakt me niet uit</button> : null}
        {index > 0 ? <button type="button" className="button button-quiet" disabled={busy} onClick={() => setIndex(index - 1)}>Vorige</button> : null}
        {!mustAnswer ? <button type="button" className="button button-quiet question-skip" disabled={busy} onClick={() => void submit(answers, true)}>Maak &rsquo;m maar</button> : null}
      </div>
    </>}
    {adjusting || answerProgress ? <RouteProgress event={answerProgress} /> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
