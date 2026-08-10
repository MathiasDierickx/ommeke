"use client";

import { Bike, LoaderCircle, Menu, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Logo } from "@/components/brand";
import { Composer, EmptyChat, Message } from "@/components/chat";
import { RouteDetail } from "@/components/route-detail";
import { Sidebar } from "@/components/sidebar";
import { apiRequest, authenticatedBlob } from "@/lib/api";
import { beginAuth, clearSession, finishAuth, loadSession, refreshSession } from "@/lib/auth";
import type { AuthSession, ChatMessage, Conversation, Route } from "@/lib/types";

export type WorkspaceView =
  | { kind: "new" }
  | { kind: "conversation"; id: string }
  | { kind: "route"; id: string };

function LoginScreen({ error }: { error?: string }) {
  const [working, setWorking] = useState<"login" | "signup" | null>(null);
  const launch = async (mode: "login" | "signup") => {
    setWorking(mode);
    try { await beginAuth(mode); } catch { setWorking(null); }
  };
  return (
    <main className="login-shell">
      <div className="login-topography" aria-hidden="true">
        <svg viewBox="0 0 800 900" preserveAspectRatio="xMidYMid slice">
          {Array.from({ length: 11 }, (_, index) => <path key={index} d={`M -80 ${140 + index * 55} C 120 ${10 + index * 78}, 270 ${260 + index * 32}, 480 ${100 + index * 67} S 760 ${170 + index * 61}, 900 ${80 + index * 73}`} />)}
          <path className="login-route-line" d="M90 730 C210 610 170 475 340 415 S520 250 690 165" />
          <circle cx="90" cy="730" r="9" /><circle cx="690" cy="165" r="9" />
        </svg>
      </div>
      <section className="login-content">
        <div className="login-brand"><Logo /><span>Lusmaker</span></div>
        <p className="eyebrow">Jouw routeatelier</p>
        <h1>Zeg waar je wil rijden.<br />Kom terug met een lus.</h1>
        <p className="login-copy">Lusmaker vertaalt je vraag naar een route die rekening houdt met afstand, ondergrond, verkeer en hoogtemeters.</p>
        {error ? <p className="auth-error" role="alert">{error}</p> : null}
        <div className="login-actions">
          <button className="button button-primary" onClick={() => launch("signup")} disabled={working !== null}>{working === "signup" ? <LoaderCircle className="spin" /> : <Bike />}Account maken</button>
          <button className="button button-quiet" onClick={() => launch("login")} disabled={working !== null}>{working === "login" ? <LoaderCircle className="spin" /> : null}Aanmelden</button>
        </div>
        <p className="login-note">Veilig aanmelden via Amazon Cognito · routes blijven privé</p>
      </section>
    </main>
  );
}

export function LusmakerApp({ view }: { view: WorkspaceView }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authError, setAuthError] = useState<string>();
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
  const messageEnd = useRef<HTMLDivElement>(null);
  const authStarted = useRef(false);

  useEffect(() => {
    if (authStarted.current) return;
    authStarted.current = true;
    let active = true;
    const resolve = async () => {
      try {
        const code = searchParams.get("code");
        const state = searchParams.get("state");
        let next = loadSession();
        if (code && state) {
          const completed = await finishAuth(code, state);
          next = completed.session;
          router.replace(completed.returnTo);
        } else if (next) {
          next = await refreshSession(next);
          if (!next) clearSession();
        }
        if (active) setSession(next);
      } catch (cause) {
        clearSession();
        if (active) setAuthError(cause instanceof Error ? cause.message : "Aanmelden mislukt.");
      } finally { if (active) setAuthReady(true); }
    };
    void resolve();
    return () => { active = false; };
  }, [router, searchParams]);

  const loadWorkspace = useCallback(async (accessToken: string) => {
    const [conversationData, routeData] = await Promise.all([
      apiRequest<{ conversations: Conversation[] }>("/api/conversations", accessToken),
      apiRequest<{ routes: Route[] }>("/api/routes", accessToken),
    ]);
    setConversations(conversationData.conversations);
    setRoutes(routeData.routes);
  }, []);

  useEffect(() => {
    if (!session) return;
    loadWorkspace(session.accessToken).catch((cause) => setError(cause instanceof Error ? cause.message : "Werkruimte laden mislukt."));
  }, [session, loadWorkspace]);

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
    apiRequest<{ route: Route }>(`/api/routes/${encodeURIComponent(view.id)}`, session.accessToken)
      .then((data) => { if (active) setSelectedRoute(data.route); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : "Route laden mislukt."); })
      .finally(() => { if (active) setLoadingRoute(false); });
    return () => { active = false; };
  }, [session, view]);

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

  if (!authReady) return <div className="app-loading"><LoaderCircle className="spin" /> Lusmaker laden…</div>;
  if (!session) return <LoginScreen error={authError} />;

  const sidebar = <Sidebar conversations={conversations} routes={routes} selectedConversation={view.kind === "conversation" ? view.id : undefined} selectedRoute={view.kind === "route" ? view.id : undefined} onConversation={openConversation} onRoute={(route) => openRoute(route.id)} onNew={openNewChat} onClose={() => setLeftOpen(false)} session={session} />;
  if (view.kind === "route") {
    return (
      <main className={`route-shell ${leftOpen ? "left-open" : ""}`}>
        <button className="mobile-scrim" onClick={() => setLeftOpen(false)} aria-label="Sluit navigatie" />
        {sidebar}
        {error ? <div className="route-error error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)} aria-label="Sluit foutmelding"><X /></button></div> : null}
        <RouteDetail route={selectedRoute} loading={loadingRoute} onDownload={() => void downloadRoute()} onRename={renameRoute} onDelete={deleteRoute} onBack={() => router.push("/")} onMenu={() => setLeftOpen(true)} />
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
