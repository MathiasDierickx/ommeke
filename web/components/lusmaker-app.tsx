"use client";

import { LoaderCircle, Menu, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { QuickPlan } from "@/components/quick-plan";
import { AuthPanel } from "@/components/auth-panel";
import { Logo } from "@/components/brand";
import { Composer, EmptyChat, Message } from "@/components/chat";
import { RouteDetail } from "@/components/route-detail";
import { RouteProgress } from "./route-progress";
import type { ProgressEvent } from "@/lib/event-stream";
import { apiStream } from "@/lib/api";
import { chatReply, mergeById, orphanState, pendingPrompt, unansweredPrompt, type PendingPrompt } from "@/lib/interaction";
import { Sidebar } from "@/components/sidebar";
import { ApiError, apiRequest, authenticatedBlob } from "@/lib/api";
import { clearStored, currentSession, signOut } from "@/lib/cognito";
import { clearOffline, registerOfflineWorker, storeRoute } from "@/lib/offline-routes";
import { safeFilename, saveBlob } from "@/lib/save-file";
import type { AuthSession, ChatMessage, Conversation, NearbyClimb, Route, RouteAdjustment } from "@/lib/types";

export type WorkspaceView =
  | { kind: "new" }
  | { kind: "conversation"; id: string }
  | { kind: "route"; id: string };

// Module-scope: reset alleen bij een volledige page-load, niet bij
// client-navigatie. Zo landt een ingelogde gebruiker bij het openen van de app
// meteen op zijn laatste route, terwijl "Nieuwe route" gewoon blijft werken.
let didInitialLanding = false;

export function LusmakerApp({ view }: { view: WorkspaceView }) {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedRoute, setSelectedRoute] = useState<Route | null>(null);
  const [loadingRoute, setLoadingRoute] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [quickBusy,setQuickBusy]=useState(false);
  const [quickHasResult, setQuickHasResult] = useState(false);
  const [answerComplete, setAnswerComplete] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent|null>(null);
  const [error, setError] = useState<string>();
  const [leftOpen, setLeftOpen] = useState(false);
  const [workspaceLoaded, setWorkspaceLoaded] = useState(false);
  const messageEnd = useRef<HTMLDivElement>(null);
  const authStarted = useRef(false);
  const sendLock = useRef(false);
  const [loadingMoreRoutes, setLoadingMoreRoutes] = useState(false);
  const moreRoutesLock = useRef(false);
  const libraryVersion = useRef(0);
  const routeLoadVersion = useRef(0);
  const [routeCursor, setRouteCursor] = useState<string | null>(null);
  // Een vraag zonder antwoord na herladen: nog bezig op de server of afgebroken.
  const [orphan, setOrphan] = useState<{ content: string; state: "running" | "interrupted" } | null>(null);
  // Antwoorden uit het startscherm worden verstuurd zodra dit gesprek geladen is.
  const [autoSend, setAutoSend] = useState<{ conversationId: string; content: string } | null>(null);
  const [loadedConversation, setLoadedConversation] = useState<string>();

  useEffect(() => {
    if (authStarted.current) return;
    authStarted.current = true;
    let active = true;
    const resolve = async () => {
      try {
        const next = await currentSession();
        if (active) setSession(next);
      } catch {
        clearStored();
      } finally { if (active) setAuthReady(true); }
    };
    void resolve();
    // Reset de vergrendeling: React Strict Mode (dev) draait deze effect twee
    // keer; zonder reset blijft de app dan eeuwig op "Lusmaker laden…" staan.
    return () => { active = false; authStarted.current = false; };
  }, []);

  const loadWorkspace = useCallback(async (accessToken: string) => {
    const version = ++libraryVersion.current;
    const [conversationData, routeData] = await Promise.all([
      apiRequest<{ conversations: Conversation[] }>("/api/conversations", accessToken),
      apiRequest<{ routes: Route[]; next_cursor?: string | null }>("/api/routes?limit=25&order=updated", accessToken),
    ]);
    if (version !== libraryVersion.current) return;
    setConversations(conversationData.conversations);
    setRoutes(routeData.routes);
    setRouteCursor(routeData.next_cursor ?? null);
    setWorkspaceLoaded(true);
  }, []);

  const loadRoute = useCallback(async (routeId: string, accessToken: string) => {
    const version = ++routeLoadVersion.current;
    const data = await apiRequest<{ route: Route }>(`/api/routes/${encodeURIComponent(routeId)}`, accessToken);
    if (version !== routeLoadVersion.current) return data.route;
    storeRoute(data.route, true); // laatst geopende routes blijven offline beschikbaar
    setSelectedRoute(data.route);
    setRoutes((current) => current.map((item) => item.id === data.route.id ? { ...item, ...data.route } : item));
    return data.route;
  }, []);

  useEffect(() => { if (session) registerOfflineWorker(); }, [session]);

  useEffect(() => {
    if (!session) return;
    loadWorkspace(session.accessToken).catch((cause) => { setWorkspaceLoaded(true); setError(cause instanceof Error ? cause.message : "Werkruimte laden mislukt."); });
  }, [session, loadWorkspace]);

  // Bij het openen van de app (volledige page-load) landt een ingelogde
  // gebruiker meteen op zijn meest recente route i.p.v. het lege startscherm.
  useEffect(() => {
    if (didInitialLanding) return;
    if (!authReady || !session || !workspaceLoaded) return;
    didInitialLanding = true;
    if (view.kind === "new" && !new URLSearchParams(window.location.search).has("new") && routes.length) {
      const latest = routes[0];
      if (latest) router.replace(`/routes/${encodeURIComponent(latest.id)}`);
    }
  }, [authReady, session, workspaceLoaded, view.kind, routes, router]);

  useEffect(() => {
    if (!session || view.kind !== "conversation") return;
    let active = true;
    setAnswerComplete(false);
    setConversationId(view.id);
    try {
      const answer = sessionStorage.getItem(`ommeke-answer:${view.id}`);
      if (answer) { setAutoSend({ conversationId: view.id, content: answer }); sessionStorage.removeItem(`ommeke-answer:${view.id}`); }
    } catch { /* Browseropslag is optioneel. */ }
    setSelectedRoute(null);
    setError(undefined);
    setOrphan(null);
    const loadMessages = () => apiRequest<{ conversation: Conversation; messages: ChatMessage[] }>(`/api/conversations/${encodeURIComponent(view.id)}/messages`, session.accessToken);
    let poll: number | undefined;
    const inspectOrphan = async (current: ChatMessage[]) => {
      const content = unansweredPrompt(current);
      if (!content || !active) { if (active) setOrphan(null); return; }
      let pending: PendingPrompt | null = null;
      try { pending = JSON.parse(sessionStorage.getItem(`ommeke-pending:${view.id}`) || "null"); } catch { /* opslag is optioneel */ }
      const sameDevice = pending?.content === content && pending.conversationId === view.id;
      const receipt = sameDevice && pending
        ? await apiRequest<{ status: string }>(`/api/conversations/${encodeURIComponent(view.id)}/requests/${encodeURIComponent(pending.id)}`, session.accessToken).catch(() => ({ status: "unknown" }))
        : null;
      if (!active) return;
      const state = orphanState(receipt?.status, sameDevice);
      if (state === "complete") {
        const fresh = await loadMessages().catch(() => null);
        if (!active) return;
        if (fresh) setMessages(fresh.messages);
        try { sessionStorage.removeItem(`ommeke-pending:${view.id}`); } catch { /* opslag is optioneel */ }
        setOrphan(null);
        return;
      }
      setOrphan({ content, state });
      // Een lopende opdracht kan nog afronden; kijk geregeld opnieuw.
      if (state === "running") poll = window.setTimeout(() => { void loadMessages().then(data => { if (active) { setMessages(data.messages); void inspectOrphan(data.messages); } }).catch(() => undefined); }, 15_000);
    };
    loadMessages()
      .then((data) => {
        if (!active) return;
        setMessages(data.messages);
        setLoadedConversation(view.id);
        void inspectOrphan(data.messages);
        setConversations((current) => current.some((item) => item.id === data.conversation.id) ? current.map((item) => item.id === data.conversation.id ? data.conversation : item) : [data.conversation, ...current]);
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Gesprek laden mislukt."); });
    return () => { active = false; window.clearTimeout(poll); };
  }, [session, view]);

  useEffect(() => {
    if (!session || view.kind !== "route") return;
    let active = true;
    setConversationId(undefined);
    setSelectedRoute(null);
    setLoadingRoute(true);
    setError(undefined);
    loadRoute(view.id, session.accessToken)
      .then(() => undefined)
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Route laden mislukt."); })
      .finally(() => { if (active) setLoadingRoute(false); });
    return () => { active = false; routeLoadVersion.current++; };
  }, [session, view, loadRoute]);

  useEffect(() => {
    if (view.kind !== "new") return;
    setQuickHasResult(false);
    setAnswerComplete(false);
    setConversationId(undefined);
    setMessages([]);
    setSelectedRoute(null);
    setError(undefined);
  }, [view]);

  // Alleen meescrollen als er een gesprek loopt; een leeg startscherm begint bovenaan.
  useEffect(() => { if (messages.length || busy) messageEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  const activeConversation = useMemo(() => conversations.find((item) => item.id === conversationId), [conversations, conversationId]);
  useEffect(() => {
    document.title = view.kind === "route" ? `${selectedRoute?.name || "Route"} — Lusmaker` : `${activeConversation?.title || "Nieuwe route"} — Lusmaker`;
  }, [activeConversation?.title, selectedRoute?.name, view.kind]);

  const openConversation = (id: string) => { setLeftOpen(false); router.push(`/chats/${encodeURIComponent(id)}`); };
  const openRoute = (id: string) => { setLeftOpen(false); router.push(`/routes/${encodeURIComponent(id)}`); };
  const openNewChat = () => { setLeftOpen(false); router.push("/?new=1"); };

  const newConversation = async (): Promise<string | undefined> => {
    if (!session) return undefined;
    try {
      const data = await apiRequest<{ conversation: Conversation }>("/api/conversations", session.accessToken, { method: "POST", body: JSON.stringify({}) });
      setConversations((current) => [data.conversation, ...current]);
      setConversationId(data.conversation.id);
      setMessages([]);
      setSelectedRoute(null);
      setLeftOpen(false);
      window.history.replaceState({}, "", `/chats/${encodeURIComponent(data.conversation.id)}`);
      return data.conversation.id;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Gesprek maken mislukt.");
      return undefined;
    }
  };

  const sendPrompt = async (starter?: string) => {
    if (!session || busy || quickBusy || sendLock.current) return;
    const content = (starter || prompt).trim();
    if (!content) return;
    sendLock.current = true;
    setBusy(true);
    setProgress(null);
    setAnswerComplete(false);
    setError(undefined);
    setOrphan(null);
    setPrompt("");
    let id = conversationId;
    if (!id) id = await newConversation();
    if (!id) { setBusy(false); sendLock.current = false; return; }
    const storageKey = `ommeke-pending:${id}`;
    let previous: PendingPrompt | null = null;
    try { previous = JSON.parse(sessionStorage.getItem(storageKey) || "null"); } catch { /* corrupte of uitgeschakelde opslag */ }
    if (previous?.content === content && previous.conversationId === id) {
      try {
        const receipt = await apiRequest<{ status: string }>(`/api/conversations/${id}/requests/${previous.id}`, session.accessToken);
        if (receipt.status === "interrupted") {
          try { sessionStorage.removeItem(storageKey); } catch { /* opslag is optioneel */ }
          setPrompt(content);
          setError("De vorige opdracht werd onderbroken. Controleer eerst je routes: er kan al een route bestaan. Opnieuw verzenden start daarna bewust een nieuwe opdracht.");
          setBusy(false);
          sendLock.current = false;
          await loadWorkspace(session.accessToken).catch(() => undefined);
          return;
        }
      } catch { /* Een onbekende status mag geen tweede uitvoering veroorzaken. */ }
    }
    const pending = pendingPrompt(previous, id, content, () => crypto.randomUUID());
    try { sessionStorage.setItem(storageKey, JSON.stringify(pending)); } catch { /* opslag is optioneel */ }
    const optimistic: ChatMessage = { id: `local-${Date.now()}`, conversation_id: id, role: "user", content, created_at: new Date().toISOString() };
    setMessages((current) => [...current, optimistic]);
    try {
      const result = chatReply(await apiStream<unknown>(`/api/conversations/${id}/messages/stream`, session.accessToken, { content, request_id: pending.id }, setProgress));
      try { sessionStorage.removeItem(storageKey); } catch { /* opslag is optioneel */ }
      setMessages((current) => mergeById(current, [result.message]));
      setProgress({stage:"library",message:"Je antwoord is klaar. Ik werk je routebibliotheek bij."});
      await loadWorkspace(session.accessToken).catch(() => setError("Je antwoord is opgeslagen. De bibliotheek kon nog niet worden vernieuwd."));
      setAnswerComplete(true);
    } catch (cause) {
      setPrompt(content);
      setMessages(current => current.filter(message => message.id !== optimistic.id));
      setError(cause instanceof Error && cause.name !== "TimeoutError" ? cause.message : "Dit duurt langer dan verwacht. Herlaad het gesprek; dezelfde vraag opnieuw verzenden maakt geen dubbele route.");
    }
    finally { setBusy(false); sendLock.current = false; }
  };

  useEffect(() => {
    if (!autoSend || busy || autoSend.conversationId !== conversationId || loadedConversation !== conversationId) return;
    const content = autoSend.content;
    setAutoSend(null);
    void sendPrompt(content);
  });

  const retryOrphan = () => {
    if (!orphan || !conversationId) return;
    try { sessionStorage.removeItem(`ommeke-pending:${conversationId}`); } catch { /* opslag is optioneel */ }
    const content = orphan.content;
    setOrphan(null);
    void sendPrompt(content);
  };

  const downloadRoute = async (format: "gpx" | "fit" = "gpx", poiKind = "alle") => {
    if (!session || !selectedRoute?.download_url) return;
    try {
      const path = format === "fit" ? `/api/routes/${selectedRoute.id}/fit` : selectedRoute.download_url;
      const separator = path.includes("?") ? "&" : "?";
      const downloadUrl = poiKind === "alle" ? path : `${path}${separator}poi=${encodeURIComponent(poiKind)}`;
      const blob = await authenticatedBlob(downloadUrl, session.accessToken);
      saveBlob(blob, safeFilename(selectedRoute.name, format));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Download mislukt."); }
  };

  const returnRoute = async (lat:number,lon:number,rest_km:number | "kortste",request_id:string,closure?:{lat:number;lon:number}) => {
    if (!session || !selectedRoute) return;
    await apiRequest(`/api/routes/${selectedRoute.id}/reroute`, session.accessToken, {method:"POST",body:JSON.stringify({lat,lon,rest_km,request_id,expected_revision:selectedRoute.revision,...(closure?{closure}:{})})});
    await loadRoute(selectedRoute.id,session.accessToken);
    await loadWorkspace(session.accessToken);
  };

  const renameRoute = async (name: string) => {
    if (!session || !selectedRoute) return;
    try {
      const data = await apiRequest<{ route: Route }>(`/api/routes/${selectedRoute.id}`, session.accessToken, { method: "PATCH", body: JSON.stringify({ name, expected_revision: selectedRoute.revision }) });
      setSelectedRoute((current) => current ? { ...current, ...data.route } : data.route);
      setRoutes((current) => current.map((item) => item.id === data.route.id ? data.route : item));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Naam wijzigen mislukt."); }
  };

  const deleteRoute = async () => {
    if (!session || !selectedRoute || !window.confirm(`Route “${selectedRoute.name}” definitief verwijderen?`)) return;
    try {
      await apiRequest<void>(`/api/routes/${selectedRoute.id}`, session.accessToken, { method: "DELETE" });
      setRoutes((current) => current.filter((item) => item.id !== selectedRoute.id));
      setSelectedRoute(null);
      router.push("/?new=1");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Route verwijderen mislukt."); }
  };

  // Stabiel verzoeknummer per aanpassing: een retry van dezelfde wijziging op dezelfde revisie hervat het receipt.
  const pendingAdjust = useRef<{ signature: string; id: string } | null>(null);
  const adjustRoute = async (adjustment: RouteAdjustment) => {
    if (!session || !selectedRoute) return;
    setError(undefined);
    const body = { ...adjustment, expected_revision: selectedRoute.revision };
    const signature = JSON.stringify([selectedRoute.id, body]);
    if (pendingAdjust.current?.signature !== signature) pendingAdjust.current = { signature, id: crypto.randomUUID() };
    try {
      const data = await apiRequest<{ route: Route }>(`/api/routes/${selectedRoute.id}/adjust`, session.accessToken, {
        method: "POST",
        body: JSON.stringify({ ...body, request_id: pendingAdjust.current.id }),
      });
      pendingAdjust.current = null;
      setSelectedRoute(data.route);
      setRoutes((current) => current.map((item) => item.id === data.route.id ? { ...item, ...data.route } : item));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError("De route is intussen gewijzigd. Je ziet nu de nieuwste versie; probeer je aanpassing opnieuw.");
        await loadRoute(selectedRoute.id, session.accessToken).catch(() => undefined);
        return;
      }
      setError(cause instanceof Error ? cause.message : "Route aanpassen mislukt.");
    }
  };

  const answerRoute = async (answers: Record<string, string>, onProgress: (event: ProgressEvent) => void) => {
    if (!session || !selectedRoute) return;
    setError(undefined);
    await apiStream(`/api/routes/${encodeURIComponent(selectedRoute.id)}/answers/stream`, session.accessToken, {
      antwoorden: answers,
      request_id: crypto.randomUUID(),
    }, onProgress);
    await loadRoute(selectedRoute.id, session.accessToken);
    await loadWorkspace(session.accessToken);
  };

  const loadNearbyClimbs = async (): Promise<NearbyClimb[]> => {
    if (!session || !selectedRoute) return [];
    try {
      const data = await apiRequest<{ climbs: NearbyClimb[] }>(`/api/routes/${selectedRoute.id}/climbs-near?radius_km=15`, session.accessToken);
      return data.climbs;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Klimmen laden mislukt.");
      return [];
    }
  };

  const shareRoute = async () => {
    if (!session || !selectedRoute) return undefined;
    if (!window.confirm("Iedereen met deze link ziet je volledige route, inclusief het precieze startpunt. Wil je deze route delen?")) return undefined;
    try {
      const result = await apiRequest<{ token: string; url: string }>(`/api/routes/${selectedRoute.id}/share`, session.accessToken, { method: "POST" });
      await loadRoute(selectedRoute.id, session.accessToken);
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Deellink maken mislukt.");
      return undefined;
    }
  };

  const unshareRoute = async () => {
    if (!session || !selectedRoute) return;
    try {
      await apiRequest(`/api/routes/${selectedRoute.id}/share`, session.accessToken, { method: "DELETE" });
      await loadRoute(selectedRoute.id, session.accessToken);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Delen stoppen mislukt."); throw cause; }
  };
  const sendFeedback = async (category: string, comment: string) => {
    if (!session || !selectedRoute) return;
    await apiRequest(`/api/routes/${selectedRoute.id}/feedback`, session.accessToken, { method: "POST", body: JSON.stringify({ category, comment }) });
  };

  if (!authReady) return <div className="app-loading"><LoaderCircle className="spin" /> Lusmaker laden…</div>;
  if (!session) return <AuthPanel onAuthenticated={setSession} />;

  const handleLogout = () => {
    const current = session;
    clearOffline();
    libraryVersion.current++;
    routeLoadVersion.current++;
    didInitialLanding = false;
    setSession(null);
    setConversations([]);
    setRoutes([]);
    void signOut(current);
    router.replace("/");
  };

  const loadMoreRoutes = async () => {
    if (!routeCursor || moreRoutesLock.current) return;
    moreRoutesLock.current = true;
    setLoadingMoreRoutes(true);
    const version = libraryVersion.current;
    try {
      const page = await apiRequest<{ routes: Route[]; next_cursor: string | null }>(`/api/routes?limit=25&order=updated&cursor=${encodeURIComponent(routeCursor)}`, session.accessToken);
      if (version !== libraryVersion.current) return;
      setRoutes(current => mergeById(current, page.routes));
      setRouteCursor(page.next_cursor);
    } catch (cause) { if (version === libraryVersion.current) setError(cause instanceof Error ? cause.message : "Routes laden mislukt."); }
    finally { moreRoutesLock.current = false; setLoadingMoreRoutes(false); }
  };
  const sidebar = <Sidebar loading={!workspaceLoaded} loadingMoreRoutes={loadingMoreRoutes} hasMoreRoutes={!!routeCursor} onMoreRoutes={() => void loadMoreRoutes()} conversations={conversations} routes={routes} selectedConversation={view.kind === "conversation" ? view.id : undefined} selectedRoute={view.kind === "route" ? view.id : undefined} onConversation={openConversation} onRoute={(route) => openRoute(route.id)} onNew={openNewChat} onClose={() => setLeftOpen(false)} session={session} onLogout={handleLogout} />;
  if (view.kind === "route") {
    return (
      <main className={`route-shell ${leftOpen ? "left-open" : ""}`}>
        <button className="mobile-scrim" onClick={() => setLeftOpen(false)} aria-label="Sluit navigatie" />
        {sidebar}
        {error ? <div className="route-error error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)} aria-label="Sluit foutmelding"><X /></button></div> : null}
        <RouteDetail route={selectedRoute} loading={loadingRoute} onDownload={kind => void downloadRoute("gpx", kind)} onDownloadFit={kind => void downloadRoute("fit", kind)} onReturn={returnRoute} onRename={renameRoute} onDelete={deleteRoute} onAdjust={adjustRoute} onAnswers={answerRoute} onLoadClimbs={loadNearbyClimbs} onShare={shareRoute} onUnshare={unshareRoute} onFeedback={sendFeedback} onBack={() => router.push("/?new=1")} onMenu={() => setLeftOpen(true)} />
      </main>
    );
  }

  return (
    <main className={`workspace ${leftOpen ? "left-open" : ""}`}>
      <button className="mobile-scrim" onClick={() => setLeftOpen(false)} aria-label="Sluit navigatie" />
      {sidebar}
      <section className="chat-panel">
        <header className="chat-head">
          <button className="icon-button mobile-menu" onClick={() => setLeftOpen(true)} aria-label="Open navigatie"><Menu /></button>
          <div><h1>{activeConversation?.title || "Nieuwe route"}</h1></div>
        </header>
        {error ? <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)} aria-label="Sluit foutmelding"><X /></button></div> : null}
        <div className="messages">
          {!messages.length && !busy && session ? <QuickPlan onResultChange={hasResult => { setQuickHasResult(hasResult); if (hasResult) void loadWorkspace(session.accessToken).catch(() => setError("Je route is klaar. De bibliotheek kon nog niet worden vernieuwd.")); }} onBusyChange={setQuickBusy} token={session.accessToken} onRoute={openRoute} onConversation={openConversation} /> : null}
          {!messages.length && !busy && !quickBusy && !quickHasResult ? <EmptyChat onStarter={(value) => void sendPrompt(value)} /> : null}
          {messages.map((message) => <Message key={message.id} message={message} onRoute={openRoute} routes={routes} onOption={(value) => void sendPrompt(value)} />)}
          {orphan && !busy ? <div className="orphan-notice" role="status">
            {orphan.state === "running"
              ? <p>Je laatste vraag wordt nog verwerkt. Het antwoord verschijnt hier vanzelf; je hoeft niets opnieuw te versturen.</p>
              : <><p>Je laatste vraag kreeg geen antwoord: de verbinding werd onderbroken. Kijk eerst in Mijn routes of er al een route bij is gekomen.</p><button onClick={retryOrphan}>Vraag opnieuw stellen</button></>}
          </div> : null}
          {busy || answerComplete ? <RouteProgress event={progress} complete={answerComplete} /> : null}
          <div ref={messageEnd} />
        </div>
        <Composer value={prompt} onChange={setPrompt} onSubmit={() => void sendPrompt()} busy={busy || quickBusy} />
      </section>
    </main>
  );
}
