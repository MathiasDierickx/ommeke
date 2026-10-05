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
import { chatReply, mergeById, pendingPrompt, type PendingPrompt } from "@/lib/interaction";
import { Sidebar } from "@/components/sidebar";
import { ApiError, apiRequest, authenticatedBlob } from "@/lib/api";
import { clearStored, currentSession, signOut } from "@/lib/cognito";
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
    return () => { active = false; };
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
    setSelectedRoute(data.route);
    setRoutes((current) => current.map((item) => item.id === data.route.id ? { ...item, ...data.route } : item));
    return data.route;
  }, []);

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
      if (answer) { setPrompt(answer); sessionStorage.removeItem(`ommeke-answer:${view.id}`); }
    } catch { /* Browseropslag is optioneel. */ }
    setSelectedRoute(null);
    setError(undefined);
    apiRequest<{ conversation: Conversation; messages: ChatMessage[] }>(`/api/conversations/${encodeURIComponent(view.id)}/messages`, session.accessToken)
      .then((data) => {
        if (!active) return;
        setMessages(data.messages);
        setConversations((current) => current.some((item) => item.id === data.conversation.id) ? current.map((item) => item.id === data.conversation.id ? data.conversation : item) : [data.conversation, ...current]);
      })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Gesprek laden mislukt."); });
    return () => { active = false; };
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

  useEffect(() => { messageEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
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

  const downloadRoute = async (format: "gpx" | "fit" = "gpx") => {
    if (!session || !selectedRoute?.download_url) return;
    try {
      const blob = await authenticatedBlob(format === "fit" ? `/api/routes/${selectedRoute.id}/fit` : selectedRoute.download_url, session.accessToken);
      saveBlob(blob, safeFilename(selectedRoute.name, format));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Download mislukt."); }
  };

  const returnRoute = async (lat:number,lon:number,rest_km:number | "kortste",request_id:string) => {
    if (!session || !selectedRoute) return;
    await apiRequest(`/api/routes/${selectedRoute.id}/reroute`, session.accessToken, {method:"POST",body:JSON.stringify({lat,lon,rest_km,request_id,expected_revision:selectedRoute.revision})});
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

  const adjustRoute = async (adjustment: RouteAdjustment) => {
    if (!session || !selectedRoute) return;
    setError(undefined);
    try {
      const data = await apiRequest<{ route: Route }>(`/api/routes/${selectedRoute.id}/adjust`, session.accessToken, {
        method: "POST",
        body: JSON.stringify({ ...adjustment, expected_revision: selectedRoute.revision }),
      });
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
    try { localStorage.removeItem("ommeke-offline-routes-v1"); } catch { /* Geen lokale opslag beschikbaar. */ }
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
        <RouteDetail route={selectedRoute} loading={loadingRoute} onDownload={() => void downloadRoute()} onDownloadFit={() => void downloadRoute("fit")} onReturn={returnRoute} onRename={renameRoute} onDelete={deleteRoute} onAdjust={adjustRoute} onLoadClimbs={loadNearbyClimbs} onShare={shareRoute} onUnshare={unshareRoute} onFeedback={sendFeedback} onBack={() => router.push("/?new=1")} onMenu={() => setLeftOpen(true)} />
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
          <div><span className="chat-kicker">Routegesprek</span><h1>{activeConversation?.title || "Nieuwe route"}</h1></div>
          <div className="model-status"><span /> Routeatelier online</div>
        </header>
        {error ? <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)} aria-label="Sluit foutmelding"><X /></button></div> : null}
        <div className="messages">
          {!messages.length && !busy && session ? <QuickPlan onResultChange={hasResult => { setQuickHasResult(hasResult); if (hasResult) void loadWorkspace(session.accessToken).catch(() => setError("Je route is klaar. De bibliotheek kon nog niet worden vernieuwd.")); }} onBusyChange={setQuickBusy} token={session.accessToken} onRoute={openRoute} onConversation={openConversation} /> : null}
          {!messages.length && !busy && !quickBusy && !quickHasResult ? <EmptyChat onStarter={(value) => void sendPrompt(value)} /> : null}
          {messages.map((message) => <Message key={message.id} message={message} onRoute={openRoute} routes={routes} onOption={(value) => void sendPrompt(value)} />)}
          {busy || answerComplete ? <RouteProgress event={progress} complete={answerComplete} /> : null}
          <div ref={messageEnd} />
        </div>
        <Composer value={prompt} onChange={setPrompt} onSubmit={() => void sendPrompt()} busy={busy || quickBusy} />
      </section>
    </main>
  );
}
