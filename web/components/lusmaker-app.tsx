"use client";

import {
  ArrowDownToLine,
  ArrowUp,
  Bike,
  Check,
  ChevronRight,
  CircleUserRound,
  Footprints,
  LoaderCircle,
  LogOut,
  Map,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Mountain,
  PanelRightClose,
  Pencil,
  Plus,
  Route as RouteIcon,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import { apiRequest, authenticatedBlob } from "@/lib/api";
import {
  beginAuth,
  clearSession,
  finishAuth,
  loadSession,
  logout,
  refreshSession,
} from "@/lib/auth";
import type { AuthSession, ChatMessage, Conversation, Route } from "@/lib/types";

const STARTERS = [
  "Maak een rustige fietsroute van 50 km vanuit Wetteren",
  "Ik wil 35 km met zoveel mogelijk hoogtemeters",
  "Plan een traillus van 12 km zonder drukke wegen",
];

function formatDate(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("nl-BE", {
    day: "numeric",
    month: "short",
  }).format(date);
}

function Logo() {
  return (
    <div className="brand-mark" aria-hidden="true">
      <span />
      <span />
    </div>
  );
}

function LoginScreen({ error }: { error?: string }) {
  const [working, setWorking] = useState<"login" | "signup" | null>(null);
  const launch = async (mode: "login" | "signup") => {
    setWorking(mode);
    try {
      await beginAuth(mode);
    } catch {
      setWorking(null);
    }
  };
  return (
    <main className="login-shell">
      <div className="login-topography" aria-hidden="true">
        <svg viewBox="0 0 800 900" preserveAspectRatio="xMidYMid slice">
          {Array.from({ length: 11 }, (_, index) => (
            <path
              key={index}
              d={`M -80 ${140 + index * 55} C 120 ${10 + index * 78}, 270 ${260 + index * 32}, 480 ${100 + index * 67} S 760 ${170 + index * 61}, 900 ${80 + index * 73}`}
            />
          ))}
          <path className="login-route-line" d="M90 730 C210 610 170 475 340 415 S520 250 690 165" />
          <circle cx="90" cy="730" r="9" />
          <circle cx="690" cy="165" r="9" />
        </svg>
      </div>
      <section className="login-content">
        <div className="login-brand"><Logo /><span>Lusmaker</span></div>
        <p className="eyebrow">Jouw routeatelier</p>
        <h1>Zeg waar je wil rijden.<br />Kom terug met een lus.</h1>
        <p className="login-copy">
          Claude vertaalt je vraag naar een route die rekening houdt met afstand,
          ondergrond, verkeer en hoogtemeters.
        </p>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="login-actions">
          <button className="button button-primary" onClick={() => launch("signup")} disabled={working !== null}>
            {working === "signup" ? <LoaderCircle className="spin" /> : <Bike />}
            Account maken
          </button>
          <button className="button button-quiet" onClick={() => launch("login")} disabled={working !== null}>
            {working === "login" ? <LoaderCircle className="spin" /> : null}
            Aanmelden
          </button>
        </div>
        <p className="login-note">Veilig aanmelden via Amazon Cognito · routes blijven privé</p>
      </section>
    </main>
  );
}

function EmptyChat({ onStarter }: { onStarter: (prompt: string) => void }) {
  return (
    <div className="empty-chat">
      <div className="route-orbit" aria-hidden="true">
        <span className="orbit-dot" />
        <RouteIcon />
      </div>
      <p className="eyebrow">Nieuwe route</p>
      <h2>Waar wil je vandaag rijden?</h2>
      <p>Beschrijf je start, afstand en wat de rit goed moet maken.</p>
      <div className="starter-list">
        {STARTERS.map((starter) => (
          <button key={starter} onClick={() => onStarter(starter)}>
            <span>{starter}</span><ArrowUp />
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({ message }: { message: ChatMessage }) {
  const assistant = message.role === "assistant";
  return (
    <article className={`message ${assistant ? "message-assistant" : "message-user"}`}>
      <div className="message-author">
        {assistant ? <Logo /> : <CircleUserRound />}
        <span>{assistant ? "Lus" : "Jij"}</span>
      </div>
      <div className="message-copy">
        {message.content.split("\n").map((line, index) => (
          <p key={`${message.id}-${index}`}>{line || "\u00a0"}</p>
        ))}
      </div>
      {message.route_ids?.length ? (
        <div className="route-made"><Check /> Route opgeslagen in je bibliotheek</div>
      ) : null}
    </article>
  );
}

function Composer({
  value,
  onChange,
  onSubmit,
  busy,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
}) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form className="composer" onSubmit={submit}>
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSubmit();
          }
        }}
        placeholder="Vraag een route of pas iets aan…"
        rows={1}
        maxLength={4000}
        disabled={busy}
        aria-label="Bericht aan Lus"
      />
      <button type="submit" disabled={busy || !value.trim()} aria-label="Verstuur bericht">
        {busy ? <LoaderCircle className="spin" /> : <Send />}
      </button>
      <span className="composer-hint">Enter om te sturen · Shift + Enter voor een nieuwe regel</span>
    </form>
  );
}

function Sidebar({
  conversations,
  routes,
  selectedConversation,
  onConversation,
  onRoute,
  onNew,
  onClose,
  session,
}: {
  conversations: Conversation[];
  routes: Route[];
  selectedConversation?: string;
  onConversation: (id: string) => void;
  onRoute: (route: Route) => void;
  onNew: () => void;
  onClose: () => void;
  session: AuthSession;
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="wordmark"><Logo /><strong>Lusmaker</strong></div>
        <button className="icon-button sidebar-close" onClick={onClose} aria-label="Sluit navigatie"><X /></button>
      </div>
      <button className="new-chat" onClick={onNew}><Plus /> Nieuwe route</button>
      <nav className="sidebar-scroll" aria-label="Gesprekken en routes">
        <section>
          <div className="nav-label"><span>Gesprekken</span><MessageSquare /></div>
          <div className="nav-items">
            {conversations.length === 0 ? <p className="nav-empty">Nog geen gesprekken</p> : null}
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                className={selectedConversation === conversation.id ? "active" : ""}
                onClick={() => onConversation(conversation.id)}
              >
                <span className="nav-title">{conversation.title}</span>
                <span className="nav-meta">{conversation.preview || formatDate(conversation.created_at)}</span>
              </button>
            ))}
          </div>
        </section>
        <section>
          <div className="nav-label"><span>Mijn routes</span><Map /></div>
          <div className="nav-items route-nav-items">
            {routes.length === 0 ? <p className="nav-empty">Je eerste route verschijnt hier</p> : null}
            {routes.map((route) => (
              <button key={route.id} onClick={() => onRoute(route)}>
                <span className="nav-title">{route.name}</span>
                <span className="nav-meta">
                  {route.total_km ? `${route.total_km.toFixed(1)} km` : "Draft"}
                  {route.elevation_gain_m ? ` · ${Math.round(route.elevation_gain_m)} hm` : ""}
                </span>
              </button>
            ))}
          </div>
        </section>
      </nav>
      <div className="profile-row">
        <span className="avatar">{(session.name || session.email || "L").slice(0, 1).toUpperCase()}</span>
        <span><strong>{session.name || "Mijn account"}</strong><small>{session.email || "Cognito gebruiker"}</small></span>
        <button className="icon-button" onClick={logout} aria-label="Afmelden"><LogOut /></button>
      </div>
    </aside>
  );
}

function RouteInspector({
  route,
  previewUrl,
  loadingPreview,
  onDownload,
  onRename,
  onDelete,
  onClose,
}: {
  route: Route | null;
  previewUrl: string | null;
  loadingPreview: boolean;
  onDownload: () => void;
  onRename: (name: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onClose: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(route?.name || "");
  useEffect(() => setName(route?.name || ""), [route?.name]);

  if (!route) {
    return (
      <aside className="inspector inspector-empty">
        <button className="icon-button inspector-close" onClick={onClose} aria-label="Sluit routedetail"><PanelRightClose /></button>
        <div className="contour-map" aria-hidden="true">
          <svg viewBox="0 0 420 520">
            {Array.from({ length: 9 }, (_, index) => (
              <path key={index} d={`M-20 ${80 + index * 49} C90 ${10 + index * 58} 175 ${160 + index * 34} 280 ${75 + index * 52} S390 ${120 + index * 45} 460 ${55 + index * 58}`} />
            ))}
            <path className="route-stroke" d="M80 420 C110 330 225 350 210 250 S265 125 350 92" />
          </svg>
        </div>
        <div className="inspector-empty-copy">
          <RouteIcon />
          <h3>Je route komt hier tot leven</h3>
          <p>Selecteer een bestaande route of beschrijf je volgende rit in de chat.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="inspector">
      <div className="inspector-head">
        <span>Routedetail</span>
        <button className="icon-button" onClick={onClose} aria-label="Sluit routedetail"><PanelRightClose /></button>
      </div>
      <div className="map-frame">
        {loadingPreview ? <div className="map-loading"><LoaderCircle className="spin" /> Kaart laden</div> : null}
        {previewUrl ? <iframe src={previewUrl} title={`Kaart van ${route.name}`} sandbox="allow-scripts" /> : null}
        {!previewUrl && !loadingPreview ? <div className="map-unavailable"><Map />Preview nog niet beschikbaar</div> : null}
      </div>
      <div className="route-detail-scroll">
        <div className="route-title-row">
          {editing ? (
            <form
              onSubmit={async (event) => {
                event.preventDefault();
                await onRename(name);
                setEditing(false);
              }}
            >
              <input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} autoFocus />
              <button aria-label="Naam bewaren"><Check /></button>
            </form>
          ) : (
            <><h2>{route.name}</h2><button className="icon-button" onClick={() => setEditing(true)} aria-label="Naam wijzigen"><Pencil /></button></>
          )}
          <span className="activity-tag">{route.activity === "trail" ? <Footprints /> : <Bike />}{route.activity}</span>
        </div>
        <p className="route-origin">Vertrek vanuit {route.start || "je gekozen startpunt"}</p>
        <dl className="route-stats">
          <div><dt>Afstand</dt><dd>{route.total_km ? route.total_km.toFixed(1) : "—"}<small> km</small></dd></div>
          <div><dt>Hoogtemeters</dt><dd>{route.elevation_gain_m ? Math.round(route.elevation_gain_m) : "—"}<small> m</small></dd></div>
          <div><dt>Klimmen</dt><dd>{route.climbs.length}</dd></div>
        </dl>
        <div className="route-actions">
          <button className="button button-primary" onClick={onDownload} disabled={!route.ready}><ArrowDownToLine /> Download GPX</button>
          <button className="button button-danger" onClick={onDelete}><Trash2 /> Verwijder</button>
        </div>
        <div className="route-footnote"><Sparkles /> Gemaakt met Claude via Amazon Bedrock</div>
      </div>
    </aside>
  );
}

export function LusmakerApp() {
  const searchParams = useSearchParams();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [authError, setAuthError] = useState<string>();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [routes, setRoutes] = useState<Route[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selectedRoute, setSelectedRoute] = useState<Route | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const messageEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    const resolve = async () => {
      try {
        const code = searchParams.get("code");
        const state = searchParams.get("state");
        let next = loadSession();
        if (code && state) {
          next = await finishAuth(code, state);
          window.history.replaceState({}, "", "/");
        } else if (next) {
          next = await refreshSession(next);
          if (!next) clearSession();
        }
        if (active) setSession(next);
      } catch (cause) {
        clearSession();
        if (active) setAuthError(cause instanceof Error ? cause.message : "Aanmelden mislukt.");
      } finally {
        if (active) setAuthReady(true);
      }
    };
    void resolve();
    return () => { active = false; };
  }, [searchParams]);

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
    loadWorkspace(session.accessToken).catch((cause) => setError(cause.message));
  }, [session, loadWorkspace]);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  const activeConversation = useMemo(
    () => conversations.find((item) => item.id === conversationId),
    [conversations, conversationId],
  );

  const openConversation = async (id: string) => {
    if (!session) return;
    setError(undefined);
    setConversationId(id);
    setLeftOpen(false);
    try {
      const data = await apiRequest<{ messages: ChatMessage[] }>(`/api/conversations/${id}/messages`, session.accessToken);
      setMessages(data.messages);
      const lastRouteId = [...data.messages].reverse().flatMap((item) => item.route_ids || [])[0];
      const route = routes.find((item) => item.id === lastRouteId);
      if (route) void openRoute(route);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Gesprek laden mislukt.");
    }
  };

  const newConversation = async (): Promise<string | undefined> => {
    if (!session) return undefined;
    try {
      const data = await apiRequest<{ conversation: Conversation }>("/api/conversations", session.accessToken, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setConversations((current) => [data.conversation, ...current]);
      setConversationId(data.conversation.id);
      setMessages([]);
      setSelectedRoute(null);
      setLeftOpen(false);
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
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      conversation_id: id,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    try {
      const result = await apiRequest<{ message: ChatMessage; route_ids: string[] }>(
        `/api/conversations/${id}/messages`,
        session.accessToken,
        { method: "POST", body: JSON.stringify({ content }) },
      );
      setMessages((current) => [...current, result.message]);
      await loadWorkspace(session.accessToken);
      if (result.route_ids.length) {
        const routeData = await apiRequest<{ route: Route }>(`/api/routes/${result.route_ids.at(-1)}`, session.accessToken);
        await openRoute(routeData.route);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Claude kon niet antwoorden.");
    } finally {
      setBusy(false);
    }
  };

  const openRoute = async (route: Route) => {
    if (!session) return;
    setSelectedRoute(route);
    setRightOpen(true);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    if (!route.preview_url) return;
    setLoadingPreview(true);
    try {
      const blob = await authenticatedBlob(route.preview_url, session.accessToken);
      setPreviewUrl(URL.createObjectURL(blob));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Preview laden mislukt.");
    } finally {
      setLoadingPreview(false);
    }
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
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Download mislukt.");
    }
  };

  const renameRoute = async (name: string) => {
    if (!session || !selectedRoute) return;
    const data = await apiRequest<{ route: Route }>(`/api/routes/${selectedRoute.id}`, session.accessToken, {
      method: "PATCH",
      body: JSON.stringify({ name, expected_revision: selectedRoute.revision }),
    });
    setSelectedRoute(data.route);
    setRoutes((current) => current.map((item) => item.id === data.route.id ? data.route : item));
  };

  const deleteRoute = async () => {
    if (!session || !selectedRoute) return;
    if (!window.confirm(`Route “${selectedRoute.name}” definitief verwijderen?`)) return;
    await apiRequest<void>(`/api/routes/${selectedRoute.id}`, session.accessToken, { method: "DELETE" });
    setRoutes((current) => current.filter((item) => item.id !== selectedRoute.id));
    setSelectedRoute(null);
    setRightOpen(false);
  };

  if (!authReady) return <div className="app-loading"><LoaderCircle className="spin" /> Lusmaker laden…</div>;
  if (!session) return <LoginScreen error={authError} />;

  return (
    <main className={`workspace ${leftOpen ? "left-open" : ""} ${rightOpen ? "right-open" : ""}`}>
      <div className="mobile-scrim" onClick={() => { setLeftOpen(false); setRightOpen(false); }} />
      <Sidebar
        conversations={conversations}
        routes={routes}
        selectedConversation={conversationId}
        onConversation={(id) => void openConversation(id)}
        onRoute={(route) => void openRoute(route)}
        onNew={() => void newConversation()}
        onClose={() => setLeftOpen(false)}
        session={session}
      />
      <section className="chat-panel">
        <header className="chat-head">
          <button className="icon-button mobile-menu" onClick={() => setLeftOpen(true)} aria-label="Open navigatie"><Menu /></button>
          <div><span className="chat-kicker">Routegesprek</span><h1>{activeConversation?.title || "Nieuwe route"}</h1></div>
          <div className="model-status"><span /> Claude via Bedrock</div>
          <button className="icon-button mobile-route" onClick={() => setRightOpen(true)} aria-label="Open routedetail"><Map /></button>
        </header>
        {error ? <div className="error-banner" role="alert"><span>{error}</span><button onClick={() => setError(undefined)}><X /></button></div> : null}
        <div className="messages">
          {messages.length === 0 ? <EmptyChat onStarter={(value) => void sendPrompt(value)} /> : null}
          {messages.map((message) => <Message key={message.id} message={message} />)}
          {busy ? (
            <div className="thinking-row"><Logo /><span>Lus tekent je route</span><i /><i /><i /></div>
          ) : null}
          <div ref={messageEnd} />
        </div>
        <Composer value={prompt} onChange={setPrompt} onSubmit={() => void sendPrompt()} busy={busy} />
      </section>
      <RouteInspector
        route={selectedRoute}
        previewUrl={previewUrl}
        loadingPreview={loadingPreview}
        onDownload={() => void downloadRoute()}
        onRename={renameRoute}
        onDelete={deleteRoute}
        onClose={() => setRightOpen(false)}
      />
    </main>
  );
}
