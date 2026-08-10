"use client";

import { LoaderCircle, Menu, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AuthPanel } from "@/components/auth-panel";
import { Logo } from "@/components/brand";
import { Composer, EmptyChat, Message } from "@/components/chat";
import { RouteDetail } from "@/components/route-detail";
import { Sidebar } from "@/components/sidebar";
import { ApiError, apiRequest, authenticatedBlob } from "@/lib/api";
import { clearStored, currentSession, signOut } from "@/lib/cognito";
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
  const [error, setError] = useState<string>();
  const [leftOpen, setLeftOpen] = useState(false);
  const [workspaceLoaded, setWorkspaceLoaded] = useState(false);
  const messageEnd = useRef<HTMLDivElement>(null);
  const authStarted = useRef(false);

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
    const [conversationData, routeData] = await Promise.all([
      apiRequest<{ conversations: Conversation[] }>("/api/conversations", accessToken),
      apiRequest<{ routes: Route[] }>("/api/routes", accessToken),
    ]);
    setConversations(conversationData.conversations);
    setRoutes(routeData.routes);
    setWorkspaceLoaded(true);
  }, []);

  const loadRoute = useCallback(async (routeId: string, accessToken: string) => {
    const data = await apiRequest<{ route: Route }>(`/api/routes/${encodeURIComponent(routeId)}`, accessToken);
    setSelectedRoute(data.route);
    setRoutes((current) => current.map((item) => item.id === data.route.id ? { ...item, ...data.route } : item));
    return data.route;
  }, []);

  useEffect(() => {
    if (!session) return;
    loadWorkspace(session.accessToken).catch((cause) => setError(cause instanceof Error ? cause.message : "Werkruimte laden mislukt."));
  }, [session, loadWorkspace]);

  // Bij het openen van de app (volledige page-load) landt een ingelogde
  // gebruiker meteen op zijn meest recente route i.p.v. het lege startscherm.
  useEffect(() => {
    if (didInitialLanding) return;
    if (!authReady || !session || !workspaceLoaded) return;
    didInitialLanding = true;
    if (view.kind === "new" && routes.length) {
      const latest = [...routes].sort((a, b) => (b.created || "").localeCompare(a.created || ""))[0];
      if (latest) router.replace(`/routes/${encodeURIComponent(latest.id)}`);
    }
  }, [authReady, session, workspaceLoaded, view.kind, routes, router]);

  useEffect(() => {
    if (!session || view.kind !== "conversation") return;
    let active = true;
    setConversationId(view.id);
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
    return () => { active = false; };
  }, [session, view, loadRoute]);

  useEffect(() => {
    if (view.kind !== "new") return;
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
  const openNewChat = () => { setLeftOpen(false); router.push("/"); };

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
    if (!session || busy) return;
    const content = (starter || prompt).trim();
    if (!content) return;
    setBusy(true);
    setError(undefined);
    setPrompt("");
    let id = conversationId;
    if (!id) id = await newConversation();
    if (!id) { setBusy(false); return; }
    const optimistic: ChatMessage = { id: `local-${Date.now()}`, conversation_id: id, role: "user", content, created_at: new Date().toISOString() };
    setMessages((current) => [...current, optimistic]);
    try {
      const result = await apiRequest<{ message: ChatMessage; route_ids: string[] }>(`/api/conversations/${id}/messages`, session.accessToken, { method: "POST", body: JSON.stringify({ content }) });
      setMessages((current) => [...current, result.message]);
      await loadWorkspace(session.accessToken);
      if (result.route_ids.length) openRoute(result.route_ids.at(-1)!);
      else router.replace(`/chats/${encodeURIComponent(id)}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Lus kon niet antwoorden."); }
    finally { setBusy(false); }
  };

  const downloadRoute = async () => {
    if (!session || !selectedRoute?.download_url) return;
    try {
      const blob = await authenticatedBlob(selectedRoute.download_url, session.accessToken);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${selectedRoute.name}.gpx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Download mislukt."); }
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
      router.push("/");
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
    try {
      const result = await apiRequest<{ token: string; url: string }>(`/api/routes/${selectedRoute.id}/share`, session.accessToken, { method: "POST" });
      await loadRoute(selectedRoute.id, session.accessToken);
      return result;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Deellink maken mislukt.");
      return undefined;
    }
  };

  if (!authReady) return <div className="app-loading"><LoaderCircle className="spin" /> Lusmaker laden…</div>;
  if (!session) return <AuthPanel onAuthenticated={setSession} />;

  const handleLogout = () => {
    const current = session;
    setSession(null);
    setConversations([]);
    setRoutes([]);
    void signOut(current);
    router.replace("/");
  };

  const sidebar = <Sidebar conversations={conversations} routes={routes} selectedConversation={view.kind === "conversation" ? view.id : undefined} selectedRoute={view.kind === "route" ? view.id : undefined} onConversation={openConversation} onRoute={(route) => openRoute(route.id)} onNew={openNewChat} onClose={() => setLeftOpen(false)} session={session} onLogout={handleLogout} />;
  if (view.kind === "route") {
    return (
      <main className={`route-shell ${leftOpen ? "left-open" : ""}`}>
        <button className="mobile-scrim" onClick={() => setLeftOpen(false)} aria-label="Sluit navigatie" />
        {sidebar}
        {error ? <div className="route-error error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)} aria-label="Sluit foutmelding"><X /></button></div> : null}
        <RouteDetail route={selectedRoute} loading={loadingRoute} onDownload={() => void downloadRoute()} onRename={renameRoute} onDelete={deleteRoute} onAdjust={adjustRoute} onLoadClimbs={loadNearbyClimbs} onShare={shareRoute} onBack={() => router.push("/")} onMenu={() => setLeftOpen(true)} />
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
          {!messages.length ? <EmptyChat onStarter={(value) => void sendPrompt(value)} /> : null}
          {messages.map((message) => <Message key={message.id} message={message} onRoute={openRoute} onOption={(value) => void sendPrompt(value)} />)}
          {busy ? <div className="thinking-row"><Logo /><span>Lus tekent je route</span><i /><i /><i /></div> : null}
          <div ref={messageEnd} />
        </div>
        <Composer value={prompt} onChange={setPrompt} onSubmit={() => void sendPrompt()} busy={busy} />
      </section>
    </main>
  );
}
