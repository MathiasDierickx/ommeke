type Saver = {
  document: Pick<Document, "createElement" | "body">;
  url: Pick<typeof URL, "createObjectURL" | "revokeObjectURL">;
  schedule: (callback: () => void, ms: number) => unknown;
};

/** Bestandsnaam zonder tekens die besturingssystemen of Chrome weigeren. */
export function safeFilename(name: string, extension: string): string {
  const base = name.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 120) || "ommeke-route";
  return `${base}.${extension}`;
}

const browserSaver = (): Saver => ({
  document,
  url: URL,
  // Los aanroepen: setTimeout als methode van dit object geeft "Illegal invocation".
  schedule: (callback, ms) => window.setTimeout(callback, ms),
});

/**
 * Bewaar een blob als download. Chrome start een download van een blob-URL
 * asynchroon; wie de URL meteen na click() intrekt, verliest de download zodra
 * Chrome eerst om toestemming voor meerdere downloads vraagt. Het anker staat
 * daarom kort in het DOM en de URL wordt pas na een minuut ingetrokken.
 */
export function saveBlob(blob: Blob, filename: string, saver: Saver = browserSaver()): void {
  const href = saver.url.createObjectURL(blob);
  const anchor = saver.document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  saver.document.body.appendChild(anchor);
  anchor.click();
  saver.schedule(() => {
    anchor.remove();
    saver.url.revokeObjectURL(href);
  }, 60_000);
}
