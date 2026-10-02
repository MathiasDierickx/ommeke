export type PendingPrompt = { id: string; content: string; conversationId: string };

export function pendingPrompt(previous: PendingPrompt | null, conversationId: string, content: string, id: () => string): PendingPrompt {
  const clean = content.trim();
  if (!clean) throw new Error("Bericht mag niet leeg zijn.");
  return previous?.conversationId === conversationId && previous.content === clean
    ? previous : { id: id(), conversationId, content: clean };
}

export function errorMessage(status: number, message?: string, retryAfter?: string | null): string {
  if (status === 429) {
    const seconds = Number(retryAfter);
    const minutes = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds / 60) : null;
    return minutes ? `Je limiet is bereikt. Probeer over ${minutes} minuten opnieuw.` : "Je limiet is bereikt. Probeer later opnieuw.";
  }
  return message || `Verzoek mislukt (${status}).`;
}

export function mergeById<T extends { id: string }>(current: T[], next: T[]): T[] {
  return [...new Map([...current, ...next].map(item => [item.id, item])).values()];
}
