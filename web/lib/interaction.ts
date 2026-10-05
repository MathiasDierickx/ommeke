export type PendingPrompt = { id: string; content: string; conversationId: string };

export function pendingPrompt(previous: PendingPrompt | null, conversationId: string, content: string, id: () => string): PendingPrompt {
  const clean = content.trim();
  if (!clean) throw new Error("Bericht mag niet leeg zijn.");
  return previous?.conversationId === conversationId && previous.content === clean
    ? previous : { id: id(), conversationId, content: clean };
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
