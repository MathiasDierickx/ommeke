import type { AuthSession } from "./types";

const SESSION_KEY = "lusmaker.auth";
const PKCE_KEY = "lusmaker.pkce";

type PendingAuth = {
  verifier: string;
  state: string;
  redirectUri: string;
  returnTo: string;
};

export type CompletedAuth = {
  session: AuthSession;
  returnTo: string;
};

function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`${name} ontbreekt in de Vercel environment`);
  return value.replace(/\/$/, "");
}

export const authConfig = {
  domain: () => required("NEXT_PUBLIC_COGNITO_DOMAIN", process.env.NEXT_PUBLIC_COGNITO_DOMAIN),
  clientId: () => required("NEXT_PUBLIC_COGNITO_CLIENT_ID", process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID),
};

function encode(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => (binary += String.fromCharCode(byte)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomValue(bytes = 32): string {
  const value = new Uint8Array(bytes);
  crypto.getRandomValues(value);
  return encode(value);
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return encode(new Uint8Array(digest));
}

function claims(token: string): Record<string, unknown> {
  try {
    const encoded = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(encoded));
  } catch {
    return {};
  }
}

function tokenSession(payload: Record<string, unknown>, previous?: AuthSession): AuthSession {
  const idToken = String(payload.id_token || previous?.idToken || "");
  const idClaims = claims(idToken);
  return {
    accessToken: String(payload.access_token),
    idToken,
    refreshToken: String(payload.refresh_token || previous?.refreshToken || "") || undefined,
    expiresAt: Date.now() + Number(payload.expires_in || 3600) * 1000,
    email: typeof idClaims.email === "string" ? idClaims.email : undefined,
    name:
      typeof idClaims.name === "string"
        ? idClaims.name
        : typeof idClaims.given_name === "string"
          ? idClaims.given_name
          : undefined,
  };
}

export function loadSession(): AuthSession | null {
  try {
    const value = sessionStorage.getItem(SESSION_KEY);
    return value ? (JSON.parse(value) as AuthSession) : null;
  } catch {
    return null;
  }
}

export function saveSession(session: AuthSession): AuthSession {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  return session;
}

export function clearSession(): void {
  sessionStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(PKCE_KEY);
}

export async function beginAuth(mode: "login" | "signup" = "login"): Promise<void> {
  const verifier = randomValue(64);
  const state = randomValue(24);
  const redirectUri = `${window.location.origin}/`;
  const returnTo = `${window.location.pathname}${window.location.search}`;
  sessionStorage.setItem(PKCE_KEY, JSON.stringify({ verifier, state, redirectUri, returnTo }));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: authConfig.clientId(),
    redirect_uri: redirectUri,
    scope: "openid email profile aws.cognito.signin.user.admin",
    state,
    code_challenge: await sha256(verifier),
    code_challenge_method: "S256",
  });
  const path = mode === "signup" ? "/signup" : "/oauth2/authorize";
  window.location.assign(`${authConfig.domain()}${path}?${params.toString()}`);
}

export async function finishAuth(code: string, state: string): Promise<CompletedAuth> {
  const value = sessionStorage.getItem(PKCE_KEY);
  if (!value) throw new Error("Aanmeldsessie verlopen. Probeer opnieuw.");
  const pending = JSON.parse(value) as PendingAuth;
  if (pending.state !== state) throw new Error("Ongeldige aanmeldstatus.");
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: authConfig.clientId(),
    code,
    redirect_uri: pending.redirectUri,
    code_verifier: pending.verifier,
  });
  const response = await fetch(`${authConfig.domain()}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) throw new Error("Aanmelden kon niet worden afgerond.");
  const session = tokenSession((await response.json()) as Record<string, unknown>);
  sessionStorage.removeItem(PKCE_KEY);
  return {
    session: saveSession(session),
    returnTo: pending.returnTo?.startsWith("/") ? pending.returnTo : "/",
  };
}

export async function refreshSession(session: AuthSession): Promise<AuthSession | null> {
  if (session.expiresAt > Date.now() + 60_000) return session;
  if (!session.refreshToken) return null;
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: authConfig.clientId(),
    refresh_token: session.refreshToken,
  });
  const response = await fetch(`${authConfig.domain()}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!response.ok) return null;
  return saveSession(tokenSession((await response.json()) as Record<string, unknown>, session));
}

export function logout(): void {
  clearSession();
  const params = new URLSearchParams({
    client_id: authConfig.clientId(),
    logout_uri: `${window.location.origin}/`,
  });
  window.location.assign(`${authConfig.domain()}/logout?${params.toString()}`);
}
