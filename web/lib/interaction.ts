export type PendingPrompt = { id: string; content: string; conversationId: string };

export function pendingPrompt(previous: PendingPrompt | null, conversationId: string, content: string, id: () => string): PendingPrompt {
  const clean = content.trim();
  if (!clean) throw new Error("Bericht mag niet leeg zijn.");
  return previous?.conversationId === conversationId && previous.content === clean
    ? previous : { id: id(), conversationId, content: clean };
}

/** Tekst van een laatste gebruikersbericht dat nog geen antwoord kreeg. */
export function unansweredPrompt(messages: { role: string; content: string }[]): string | null {
  const last = messages[messages.length - 1];
  return last?.role === "user" ? last.content.trim() || null : null;
}

export type OrphanState = "running" | "interrupted" | "complete";

/** Vertaal de serverstatus van een opdracht naar wat de UI moet tonen. */
export function orphanState(receipt: string | null | undefined, sameDevice: boolean): OrphanState {
  if (!sameDevice) return "interrupted";
  if (receipt === "complete") return "complete";
  if (receipt === "running") return "running";
  return "interrupted";
}

export function errorMessage(status: number, message?: string, retryAfter?: string | null, code?: string): string {
  if (status === 401) return "Je sessie is verlopen. Herlaad de app om opnieuw in te loggen; je routes blijven bewaard.";
  if (status === 429) {
    // Eigen quotumteksten noemen de limiet en het resetmoment; andere 429's
    // (bv. een drukke modelprovider) tonen we generiek.
    if (code === "quota_exceeded" && message) return message;
    const seconds = Number(retryAfter);
    const minutes = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds / 60) : null;
    if (!minutes) return "Het is even te druk. Probeer later opnieuw.";
    const wait = minutes >= 90 ? `${Math.round(minutes / 60)} uur` : `${minutes} minuten`;
    return `Het is even te druk. Probeer over ${wait} opnieuw.`;
  }
  return message || `Verzoek mislukt (${status}).`;
}

export const OUT_OF_COVERAGE = "buiten_gebied";

/** Server zegt: start, anker of via-punt ligt buiten het gedekte gebied (HTTP 422). */
export function isOutOfCoverage(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { code?: unknown }).code === OUT_OF_COVERAGE;
}

export function mergeById<T extends { id: string }>(current: T[], next: T[]): T[] {
  return [...new Map([...current, ...next].map(item => [item.id, item])).values()];
}

export function chatReply(value: unknown): { message: { id: string; conversation_id: string; role: "assistant"; content: string; created_at: string }; route_ids: string[]; ready_route_ids?: string[] } {
  const reply = value as { message?: Record<string, unknown>; route_ids?: unknown; ready_route_ids?: unknown } | null;
  const message = reply?.message;
  if (!message || typeof message.id !== "string" || typeof message.content !== "string" || !message.content.trim() || message.role !== "assistant" || typeof message.conversation_id !== "string" || typeof message.created_at !== "string" || !Array.isArray(reply?.route_ids) || !reply.route_ids.every(id => typeof id === "string")) {
    throw new Error("De server gaf geen volledig chatantwoord terug. Herlaad het gesprek en controleer je routes voordat je opnieuw probeert.");
  }
  if (reply?.ready_route_ids !== undefined && (!Array.isArray(reply.ready_route_ids) || !reply.ready_route_ids.every(id => typeof id === "string"))) {
    throw new Error("De server gaf een ongeldige routestatus terug. Herlaad het gesprek.");
  }
  return reply as ReturnType<typeof chatReply>;
}

/**
 * Browserfouten ("signal timed out", "Failed to fetch") zijn Engels en zeggen
 * niets over herstel. Vertaal ze; de naam blijft voor wie op TimeoutError test.
 */
export function networkError(cause: unknown): unknown {
  if (!(cause instanceof Error)) return cause;
  if (cause.name === "TimeoutError" || cause.name === "AbortError") {
    const error = new Error("Dit duurt langer dan verwacht. Je route kan nog worden afgewerkt: kijk zo meteen in Mijn routes. Opnieuw proberen maakt geen dubbele route.");
    error.name = cause.name;
    return error;
  }
  if (cause.name === "TypeError" && /fetch|network|load failed/i.test(cause.message)) {
    return new Error("Geen verbinding met Ommeke. Controleer je internet en probeer opnieuw; je routes blijven bewaard.");
  }
  return cause;
}
