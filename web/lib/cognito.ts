import type { AuthSession } from "./types";

// Self-hosted Cognito-auth: we praten rechtstreeks met de Cognito Identity
// Provider-API (geen Hosted UI, geen extra dependency) zodat login/registratie/
// wachtwoord-reset volledig in onze eigen, on-brand UI leven. De web-client is
// public (geen secret), dus dit kan veilig vanuit de browser over HTTPS.

const SESSION_KEY = "lusmaker.auth";

function required(name: string, value: string | undefined): string {
  if (!value) throw new Error(`${name} ontbreekt in de Vercel environment`);
  return value.replace(/\/$/, "");
}

function clientId(): string {
  return required("NEXT_PUBLIC_COGNITO_CLIENT_ID", process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID);
}

function region(): string {
  const explicit = process.env.NEXT_PUBLIC_COGNITO_REGION;
  if (explicit) return explicit;
  const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN || "";
  const match = domain.match(/\.auth\.([a-z0-9-]+)\.amazoncognito\.com/);
  return match ? match[1] : "eu-west-1";
}

function endpoint(): string {
  return `https://cognito-idp.${region()}.amazonaws.com/`;
}

// --- Nette Nederlandse foutmeldingen -------------------------------------

const MESSAGES: Record<string, string> = {
  NotAuthorizedException: "E-mailadres of wachtwoord klopt niet.",
  UserNotFoundException: "E-mailadres of wachtwoord klopt niet.",
  UserNotConfirmedException: "Je account is nog niet bevestigd. Vul de code uit je mail in.",
  UsernameExistsException: "Er bestaat al een account met dit e-mailadres.",
  CodeMismatchException: "Die code klopt niet. Controleer je mail en probeer opnieuw.",
  ExpiredCodeException: "Die code is verlopen. Vraag een nieuwe aan.",
  InvalidPasswordException:
    "Wachtwoord voldoet niet: min. 12 tekens met een hoofdletter, kleine letter, cijfer en symbool.",
  InvalidParameterException: "Controleer de ingevulde gegevens.",
  LimitExceededException: "Te veel pogingen. Wacht even en probeer opnieuw.",
  TooManyRequestsException: "Te veel pogingen. Wacht even en probeer opnieuw.",
  TooManyFailedAttemptsException: "Te veel mislukte pogingen. Wacht even en probeer opnieuw.",
  CodeDeliveryFailureException: "De code kon niet verstuurd worden. Probeer het later opnieuw.",
};

export class AuthError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

type Challenge = { challenge: string };

async function call(target: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(endpoint(), {
      method: "POST",
      headers: {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new AuthError("NetworkError", "Geen verbinding. Controleer je internet en probeer opnieuw.");
  }
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const raw = String(payload.__type || payload.code || "UnknownException");
    const code = raw.includes("#") ? raw.split("#").pop()! : raw;
    const message = MESSAGES[code] || (typeof payload.message === "string" ? payload.message : "Er ging iets mis. Probeer opnieuw.");
    throw new AuthError(code, message);
  }
  return payload;
}

// --- Sessie-opslag (localStorage: blijft over app-herstarts heen) ---------

function claims(token: string): Record<string, unknown> {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(part));
  } catch {
    return {};
  }
}

function toSession(result: Record<string, unknown>, previous?: AuthSession): AuthSession {
  const idToken = String(result.IdToken || previous?.idToken || "");
  const idClaims = claims(idToken);
  const name =
    typeof idClaims.name === "string"
      ? idClaims.name
      : typeof idClaims.given_name === "string"
        ? idClaims.given_name
        : undefined;
  return {
    accessToken: String(result.AccessToken),
    idToken,
    refreshToken: String(result.RefreshToken || previous?.refreshToken || "") || undefined,
    expiresAt: Date.now() + Number(result.ExpiresIn || 3600) * 1000,
    email: typeof idClaims.email === "string" ? idClaims.email : previous?.email,
    name,
  };
}

export function storedSession(): AuthSession | null {
  try {
    const value = localStorage.getItem(SESSION_KEY);
    return value ? (JSON.parse(value) as AuthSession) : null;
  } catch {
    return null;
  }
}

function store(session: AuthSession): AuthSession {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* opslag geweigerd (private mode) — sessie leeft dan alleen in geheugen */
  }
  return session;
}

export function clearStored(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
    // ruim ook een eventuele oude sessionStorage-sleutel op
    sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* noop */
  }
}

// --- Publieke auth-flows ---------------------------------------------------

export async function signIn(email: string, password: string): Promise<AuthSession | Challenge> {
  const payload = await call("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: clientId(),
    AuthParameters: { USERNAME: email.trim(), PASSWORD: password },
  });
  const result = payload.AuthenticationResult as Record<string, unknown> | undefined;
  if (result) return store(toSession(result));
  // Uitdaging (bv. MFA) — nog niet ondersteund in deze UI.
  return { challenge: String(payload.ChallengeName || "UNKNOWN") };
}

export async function signUp(email: string, password: string): Promise<void> {
  await call("SignUp", {
    ClientId: clientId(),
    Username: email.trim(),
    Password: password,
    UserAttributes: [{ Name: "email", Value: email.trim() }],
  });
}

export async function confirmSignUp(email: string, code: string): Promise<void> {
  await call("ConfirmSignUp", {
    ClientId: clientId(),
    Username: email.trim(),
    ConfirmationCode: code.trim(),
  });
}

export async function resendSignUpCode(email: string): Promise<void> {
  await call("ResendConfirmationCode", { ClientId: clientId(), Username: email.trim() });
}

export async function forgotPassword(email: string): Promise<void> {
  await call("ForgotPassword", { ClientId: clientId(), Username: email.trim() });
}

export async function confirmForgotPassword(email: string, code: string, password: string): Promise<void> {
  await call("ConfirmForgotPassword", {
    ClientId: clientId(),
    Username: email.trim(),
    ConfirmationCode: code.trim(),
    Password: password,
  });
}

export async function refresh(session: AuthSession): Promise<AuthSession | null> {
  if (session.expiresAt > Date.now() + 60_000) return session;
  if (!session.refreshToken) return null;
  try {
    const payload = await call("InitiateAuth", {
      AuthFlow: "REFRESH_TOKEN_AUTH",
      ClientId: clientId(),
      AuthParameters: { REFRESH_TOKEN: session.refreshToken },
    });
    const result = payload.AuthenticationResult as Record<string, unknown> | undefined;
    return result ? store(toSession(result, session)) : null;
  } catch {
    return null;
  }
}

/** Laad de bewaarde sessie en vernieuw ze indien nodig. */
export async function currentSession(): Promise<AuthSession | null> {
  const stored = storedSession();
  if (!stored) return null;
  const fresh = await refresh(stored);
  if (!fresh) clearStored();
  return fresh;
}

export async function signOut(session: AuthSession | null): Promise<void> {
  if (session?.accessToken) {
    try {
      await call("GlobalSignOut", { AccessToken: session.accessToken });
    } catch {
      /* token mogelijk al verlopen — lokaal opruimen volstaat */
    }
  }
  clearStored();
}
