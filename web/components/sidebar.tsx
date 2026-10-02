"use client";

import { useMemo, useState } from "react";
import { filterRoutes } from "@/lib/route-library";

import { LogOut, Map, MessageSquare, Plus, X } from "lucide-react";

import type { AuthSession, Conversation, Route } from "@/lib/types";
import { AccountControls } from "./account-controls";
import { Logo } from "./brand";

function formatDate(value?: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("nl-BE", { day: "numeric", month: "short" }).format(date);
}

export function Sidebar({ conversations, routes, selectedConversation, selectedRoute, onConversation, onRoute, onNew, onClose, session, onLogout, hasMoreRoutes, onMoreRoutes, accountSlot, loadingMoreRoutes }: {
  conversations: Conversation[];
  routes: Route[];
  selectedConversation?: string;
  selectedRoute?: string;
  onConversation: (id: string) => void;
  onRoute: (route: Route) => void;
  onNew: () => void;
  onClose: () => void;
  session: AuthSession;
  onLogout: () => void;
  accountSlot?: React.ReactNode;
  hasMoreRoutes?: boolean;
  loadingMoreRoutes?: boolean;
  onMoreRoutes?: () => void;
}) {
  const [query, setQuery] = useState("");
  const [activity, setActivity] = useState<"all" | "fietsen" | "trail">("all");
  const visibleRoutes = useMemo(() => filterRoutes(routes, query, activity), [routes, query, activity]);
  return (
    <aside className="sidebar">
      <div className="sidebar-head"><div className="wordmark"><Logo /><strong>Lusmaker</strong></div><button className="icon-button sidebar-close" onClick={onClose} aria-label="Sluit navigatie"><X /></button></div>
      <button className="new-chat" onClick={onNew}><Plus /> Nieuwe route</button>
      <nav className="sidebar-scroll" aria-label="Gesprekken en routes">
        <section>
          <div className="nav-label"><span>Gesprekken</span><MessageSquare /></div>
          <div className="nav-items conversation-nav-items">
            {!conversations.length ? <p className="nav-empty">Nog geen gesprekken</p> : null}
            {conversations.slice(0, 15).map((conversation) => <button key={conversation.id} className={selectedConversation === conversation.id ? "active" : ""} onClick={() => onConversation(conversation.id)}><span className="nav-title">{conversation.title}</span><span className="nav-meta">{conversation.preview || formatDate(conversation.created_at)}</span></button>)}
          </div>
        </section>
        <section>
          <div className="nav-label"><span>Mijn routes</span><Map /></div>
          <div className="library-filters">
            <label>Zoek in geladen routes<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Naam of startplaats" /></label>
            <label>Activiteit<select value={activity} onChange={event => setActivity(event.target.value as typeof activity)}><option value="all">Alle activiteiten</option><option value="fietsen">Fietsen</option><option value="trail">Trail</option></select></label>
            <p className="nav-empty" role="status">{visibleRoutes.length} van {routes.length} geladen routes · recent gewijzigd eerst</p>
          </div>
          <div className="nav-items route-nav-items">
            {routes.length > 0 && !visibleRoutes.length ? <p className="nav-empty">Geen overeenkomst in de geladen routes. Pas je zoekterm aan of laad meer routes.</p> : null}
            {!routes.length ? <p className="nav-empty">Je eerste route verschijnt hier</p> : null}
            {visibleRoutes.map((route) => <button key={route.id} className={selectedRoute === route.id ? "active" : ""} onClick={() => onRoute(route)}><span className="nav-title">{route.name}</span><span className="nav-meta">{route.ready && route.total_km != null ? `${route.total_km.toFixed(1)} km` : "Concept"}{route.elevation_gain_m != null ? ` · ${Math.round(route.elevation_gain_m)} hm` : ""}</span></button>)}
          </div>
          {hasMoreRoutes ? <button className="new-chat" disabled={loadingMoreRoutes} onClick={onMoreRoutes}>{loadingMoreRoutes ? "Routes laden…" : "Meer routes laden"}</button> : null}
        </section>
        {accountSlot ?? <AccountControls token={session.accessToken} onDeleted={onLogout} />}
      </nav>
      <div className="profile-row"><span className="avatar">{(session.name || session.email || "L").slice(0, 1).toUpperCase()}</span><span><strong>{session.name || "Mijn account"}</strong><small>{session.email || "Cognito-gebruiker"}</small></span><button className="icon-button" onClick={onLogout} aria-label="Afmelden"><LogOut /></button></div>
    </aside>
  );
}
