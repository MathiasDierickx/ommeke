"use client";

import { useEffect, useRef, useState } from "react";
import type { Route } from "@/lib/types";
import { optionLabel, type RouteQuestion } from "@/lib/question-labels";
import type { ProgressEvent } from "@/lib/event-stream";
import { RouteProgress } from "./route-progress";

export type AnswerRoute = (answers: Record<string, string>, onProgress: (event: ProgressEvent) => void) => Promise<void>;

export function RouteQuestions({ route, onAnswers, disabled = false, submitLabel = "Route berekenen", onBusyChange }: { onBusyChange?: (busy: boolean) => void; route: Route; onAnswers: AnswerRoute; disabled?: boolean; submitLabel?: string }) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [adjusting, setAdjusting] = useState(false);
  const [answerProgress, setAnswerProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState<string>();
  const lock = useRef(false);
  const questions = JSON.stringify(route.vragen);
  useEffect(() => { setAnswers({}); setAnswerProgress(null); setError(undefined); }, [route.id, route.revision, questions]);
  if (!route.vragen?.length) return null;
  return <section className="route-pending" aria-label="Open routevragen">
    <h3>Deze route wacht nog op je keuzes</h3>
    {route.vragen.map((question: RouteQuestion) => <div className="planner-question" role="radiogroup" aria-label={question.vraag} key={question.id || question.vraag}>
      <p>{question.vraag}</p>{question.reden ? <small>{question.reden}</small> : null}
      <div className="goal-options">{Object.keys(question.opties).map(option => <label key={option} className="choice-chip choice-chip-quiet">
        <input disabled={disabled || adjusting} type="radio" name={`route-vraag-${route.id}-${question.id || question.vraag}`} value={option} checked={answers[question.id || question.vraag] === option} onChange={() => setAnswers(current => ({ ...current, [question.id || question.vraag]: option }))} />
        <span>{optionLabel(question, option)}</span>
      </label>)}</div>
    </div>)}
    <button className="button button-primary" disabled={disabled || adjusting || route.vragen.some(q => !answers[q.id || q.vraag])} onClick={async () => {
      if (disabled || lock.current || !route.vragen) return;
      lock.current = true; setError(undefined);
      setAdjusting(true); onBusyChange?.(true); setAnswerProgress(null);
      try {
        await onAnswers(Object.fromEntries(route.vragen.map(q => [q.id || q.vraag, answers[q.id || q.vraag]])), setAnswerProgress);
        setAnswers({});
      }
      catch (cause) { setError(cause instanceof Error ? cause.message : "Route berekenen mislukt. Probeer opnieuw."); }
      finally { lock.current = false; setAdjusting(false); onBusyChange?.(false); }
    }}>{adjusting ? "Route wordt berekend…" : submitLabel}</button>
    {adjusting || answerProgress ? <RouteProgress event={answerProgress} /> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
