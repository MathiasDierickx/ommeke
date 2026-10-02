export class StreamFailure extends Error {
  constructor(message: string) { super(message); this.name = "StreamFailure"; }
}

export type ProgressEvent = { stage: string; message: string };

export async function readEventStream<T>(body: ReadableStream<Uint8Array>, onProgress: (value: ProgressEvent) => void): Promise<T> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const {value, done} = await reader.read();
      buffer = (buffer + decoder.decode(value, {stream: !done})).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0,end); buffer = buffer.slice(end+2);
        const lines = chunk.split("\n");
        const event = lines.find(line=>line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter(line=>line.startsWith("data:")).map(line=>line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const parsed = JSON.parse(data);
        if(event === "progress" && typeof parsed.stage === "string" && typeof parsed.message === "string") onProgress(parsed);
        if(event === "error") throw new StreamFailure(parsed.error || "De opdracht is mislukt. Herlaad je gesprek.");
        if(event === "result") return parsed as T;
      }
      if(done) throw new Error("De verbinding werd onderbroken. Herlaad het gesprek; dezelfde opdracht opnieuw verzenden maakt geen dubbele route.");
      if(buffer.length>2_000_000) throw new Error("Het serverantwoord is te groot.");
    }
  } finally { await reader.cancel().catch(()=>undefined); reader.releaseLock(); }
}
