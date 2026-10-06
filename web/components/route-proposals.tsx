"use client";

import { useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import type { ProposalResult, RouteProposal } from "@/lib/types";
import type { ProgressEvent } from "@/lib/event-stream";
import { RouteProgress } from "./route-progress";

export function RouteProposals({ routeId, proposals, token, disabled = false, onApplied, onBusyChange, onProgress }: {
  routeId: string; proposals?: RouteProposal[]; token: string; disabled?: boolean;
  onApplied: (data: ProposalResult, proposal: RouteProposal) => void;
  onBusyChange?: (busy: boolean) => void;
  onProgress?: (event: ProgressEvent) => void;
}) {
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [error, setError] = useState("");

  async function apply(proposal: RouteProposal) {
    if (disabled || lock.current) return;
    const signature = JSON.stringify([routeId, proposal.adjust_route]);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    lock.current = true; setBusy(true); onBusyChange?.(true); setError("");
    const event = { stage: "adjusting", message: `Ik ${proposal.titel.replace(/^Voeg\s+/i, "voeg ")} en bereken je route opnieuw.` };
    setProgress(event); onProgress?.(event);
    try {
      const data = await apiRequest<ProposalResult>(`/api/routes/${encodeURIComponent(routeId)}/adjust`, token, {
        method: "POST", body: JSON.stringify({ ...proposal.adjust_route, request_id: pending.current.id }),
      });
      pending.current = null;
      onApplied(data, proposal);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Het voorstel kon niet worden toegepast."); }
    finally { lock.current = false; setBusy(false); onBusyChange?.(false); }
  }

  if (!proposals?.length) return null;
  return <>
    {busy && !onProgress ? <RouteProgress event={progress} /> : null}
    <div className="quick-proposals" role="group" aria-label="Voorstellen voor je route">
      <p className="quick-proposals-title">Zin om er iets aan toe te voegen?</p>
      {proposals.map(proposal => <div className="quick-proposal" key={proposal.titel}>
        <button className="quick-proposal-button" disabled={disabled || busy} onClick={() => void apply(proposal)}>{proposal.titel}</button>
        <small>{proposal.uitleg}</small>
      </div>)}
    </div>
    {error ? <p role="alert">{error}</p> : null}
  </>;
}
