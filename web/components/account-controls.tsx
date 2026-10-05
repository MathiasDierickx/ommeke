"use client";
import { useState } from "react";
import { apiRequest, authenticatedBlob } from "@/lib/api";
import { saveBlob } from "@/lib/save-file";

export function AccountControls({ token, onDeleted }: { token: string; onDeleted: () => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const blob = await authenticatedBlob("/api/account/export", token);
      saveBlob(blob, "ommeke-gegevens.zip");
      setMessage("Je gegevens zijn geëxporteerd.");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Export mislukt."); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (window.prompt("Je account, routes, profielen en gesprekken worden definitief gewist. Typ VERWIJDER om te bevestigen.") !== "VERWIJDER") return;
    setBusy(true);
    try {
      const result = await apiRequest<{ status: string; retry_after?: number }>("/api/account", token, { method: "DELETE", body: JSON.stringify({ confirmation: "VERWIJDER" }) });
      if (result.status === "deleted") onDeleted();
      else setMessage(`Je account is geblokkeerd voor nieuwe opdrachten. Klik over ${Math.ceil((result.retry_after || 960) / 60)} minuten nogmaals op verwijderen om het wissen af te ronden. Je kunt eerst nog exporteren.`);
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "Verwijderen mislukt; probeer opnieuw."); }
    finally { setBusy(false); }
  };
  return <details className="account-controls"><summary>Mijn gegevens</summary><p>Exporteer je gegevens of verwijder je account. Delen maakt je precieze route zichtbaar.</p><button disabled={busy} onClick={() => void download()}>Gegevens exporteren</button><button disabled={busy} onClick={() => void remove()}>Account verwijderen</button><p role="status">{message}</p></details>;
}
