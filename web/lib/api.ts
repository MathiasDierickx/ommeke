import { errorMessage } from "./interaction";

function apiBase(): string {
  const value = process.env.NEXT_PUBLIC_API_URL;
  if (!value) throw new Error("NEXT_PUBLIC_API_URL ontbreekt in de Vercel environment");
  return value.replace(/\/$/, "");
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(errorMessage(response.status, payload.error, response.headers.get("Retry-After")), response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiRequest<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    signal: init.signal ?? AbortSignal.timeout(240_000),
    ...init,
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  return responseJson<T>(response);
}

export async function publicApiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    signal: init.signal ?? AbortSignal.timeout(240_000),
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  return responseJson<T>(response);
}

export async function authenticatedBlob(path: string, token: string): Promise<Blob> {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Routebestand kon niet worden geladen.");
  return response.blob();
}

export async function apiStream<T>(path: string, token: string, body: unknown, onProgress: (value: import('./event-stream').ProgressEvent) => void): Promise<T> {
  const { readEventStream } = await import('./event-stream');
  const response = await fetch(`${apiBase()}${path}`, {
    method: 'POST', signal: AbortSignal.timeout(850_000),
    headers: {Accept:'text/event-stream', 'Content-Type':'application/json', Authorization:`Bearer ${token}`},
    body: JSON.stringify(body),
  });
  if(!response.ok) return responseJson<T>(response);
  if(!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) throw new Error('Voortgang is tijdelijk niet beschikbaar. Herlaad het gesprek voordat je opnieuw probeert.');
  return readEventStream<T>(response.body,onProgress);
}
