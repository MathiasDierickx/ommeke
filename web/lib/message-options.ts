import type { ChatMessage } from "./types";

export function messageOptions(message: Pick<ChatMessage, "role" | "content">): string[] {
  if (message.role !== "assistant" || !message.content.includes("?")) return [];
  const options = message.content.split("\n")
    .filter(line => !/`|adjust_route\s*\(|\/tmp\/|\.gpx\b|\.html\b/i.test(line))
    .map(line => line.match(/^\s*(?:[-•]|\d+[.)])\s+(.+)$/)?.[1]
      ?.replace(/[*_`]/g, "")
      .replace(/\s*[–—-]\s*lat\b.*\blon\b.*$/i, "").trim())
    .filter((value): value is string => Boolean(value));
  return options.length >= 2 && options.length <= 6 ? options : [];
}
