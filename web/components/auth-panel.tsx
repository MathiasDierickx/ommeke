"use client";

import { LoaderCircle } from "lucide-react";
import { FormEvent, useState } from "react";

import { Logo } from "@/components/brand";
import {
  AuthError,
  confirmForgotPassword,
  confirmSignUp,
  forgotPassword,
  resendSignUpCode,
  signIn,
  signUp,
} from "@/lib/cognito";
import type { AuthSession } from "@/lib/types";

type View = "login" | "signup" | "confirm" | "forgot" | "reset";

const TITLES: Record<View, { eyebrow: string; heading: string; copy: string }> = {
  login: {
    eyebrow: "Jouw routeatelier",
    heading: "Welkom terug.",
    copy: "Meld je aan en ga verder waar je gebleven was.",
  },
  signup: {
    eyebrow: "Jouw routeatelier",
    heading: "Maak je account.",
    copy: "Zeg waar je wil rijden, kom terug met een lus die rekening houdt met afstand, ondergrond en hoogtemeters.",
  },
  confirm: {
    eyebrow: "Nog één stap",
    heading: "Bevestig je mail.",
    copy: "We stuurden een code naar je e-mailadres. Vul die hieronder in.",
  },
  forgot: {
    eyebrow: "Wachtwoord vergeten",
    heading: "Geen probleem.",
    copy: "Vul je e-mailadres in, dan sturen we een code om een nieuw wachtwoord te kiezen.",
  },
  reset: {
    eyebrow: "Nieuw wachtwoord",
    heading: "Kies een nieuw wachtwoord.",
    copy: "Vul de code uit je mail in en stel een nieuw wachtwoord in.",
  },
};

function message(cause: unknown): string {
  if (cause instanceof AuthError) return cause.message;
  if (cause instanceof Error) return cause.message;
  return "Er ging iets mis. Probeer opnieuw.";
}

export function AuthPanel({ onAuthenticated }: { onAuthenticated: (session: AuthSession) => void }) {
  const [view, setView] = useState<View>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();

  const go = (next: View) => {
    setError(undefined);
    setNotice(undefined);
    setCode("");
    if (next === "login" || next === "signup") setPassword("");
    setView(next);
  };

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(undefined);
    try {
      await fn();
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  };

  const onLogin = (event: FormEvent) => {
    event.preventDefault();
    void guard(async () => {
      const result = await signIn(email, password);
      if ("challenge" in result) {
        setError("Dit account vereist extra verificatie die nog niet ondersteund wordt.");
        return;
      }
      onAuthenticated(result);
    });
  };

  const onSignup = (event: FormEvent) => {
    event.preventDefault();
    void guard(async () => {
      await signUp(email, password);
      setNotice("We stuurden een bevestigingscode naar je mail.");
      setView("confirm");
    });
  };

  const onConfirm = (event: FormEvent) => {
    event.preventDefault();
    void guard(async () => {
      await confirmSignUp(email, code);
      // Meteen inloggen als we het wachtwoord nog in de hand hebben.
      if (password) {
        const result = await signIn(email, password);
        if (!("challenge" in result)) {
          onAuthenticated(result);
          return;
        }
      }
      setNotice("Je account is bevestigd. Meld je nu aan.");
      go("login");
    });
  };

  const onForgot = (event: FormEvent) => {
    event.preventDefault();
    void guard(async () => {
      await forgotPassword(email);
      setNotice("We stuurden een herstelcode naar je mail.");
      setView("reset");
    });
  };

  const onReset = (event: FormEvent) => {
    event.preventDefault();
    void guard(async () => {
      await confirmForgotPassword(email, code, password);
      setNotice("Je wachtwoord is aangepast. Meld je nu aan.");
      go("login");
    });
  };

  const resend = () =>
    void guard(async () => {
      await resendSignUpCode(email);
      setNotice("Nieuwe code verstuurd.");
    });

  const meta = TITLES[view];

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
        <div className="login-brand">
          <Logo />
          <span>Lusmaker</span>
        </div>
        <p className="eyebrow">{meta.eyebrow}</p>
        <h1>{meta.heading}</h1>
        <p className="login-copy">{meta.copy}</p>

        {notice ? (
          <p className="auth-success" role="status">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p className="auth-error" role="alert">
            {error}
          </p>
        ) : null}

        {view === "login" ? (
          <form className="auth-form" onSubmit={onLogin}>
            <EmailField value={email} onChange={setEmail} />
            <PasswordField value={password} onChange={setPassword} autoComplete="current-password" />
            <button className="button button-primary" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : null}
              Aanmelden
            </button>
            <div className="auth-links">
              <button type="button" className="auth-link" onClick={() => go("forgot")}>
                Wachtwoord vergeten?
              </button>
            </div>
            <p className="auth-switch">
              Nog geen account?{" "}
              <button type="button" className="auth-link" onClick={() => go("signup")}>
                Maak er een
              </button>
            </p>
          </form>
        ) : null}

        {view === "signup" ? (
          <form className="auth-form" onSubmit={onSignup}>
            <EmailField value={email} onChange={setEmail} />
            <PasswordField value={password} onChange={setPassword} autoComplete="new-password" />
            <p className="auth-hint">Minstens 12 tekens, met een hoofdletter, kleine letter, cijfer en symbool.</p>
            <button className="button button-primary" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : null}
              Account maken
            </button>
            <p className="auth-switch">
              Heb je al een account?{" "}
              <button type="button" className="auth-link" onClick={() => go("login")}>
                Aanmelden
              </button>
            </p>
          </form>
        ) : null}

        {view === "confirm" ? (
          <form className="auth-form" onSubmit={onConfirm}>
            <EmailField value={email} onChange={setEmail} />
            <CodeField value={code} onChange={setCode} />
            <button className="button button-primary" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : null}
              Bevestigen
            </button>
            <div className="auth-links">
              <button type="button" className="auth-link" onClick={resend} disabled={busy}>
                Geen code ontvangen? Stuur opnieuw
              </button>
            </div>
            <p className="auth-switch">
              <button type="button" className="auth-link" onClick={() => go("login")}>
                Terug naar aanmelden
              </button>
            </p>
          </form>
        ) : null}

        {view === "forgot" ? (
          <form className="auth-form" onSubmit={onForgot}>
            <EmailField value={email} onChange={setEmail} />
            <button className="button button-primary" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : null}
              Stuur herstelcode
            </button>
            <p className="auth-switch">
              <button type="button" className="auth-link" onClick={() => go("login")}>
                Terug naar aanmelden
              </button>
            </p>
          </form>
        ) : null}

        {view === "reset" ? (
          <form className="auth-form" onSubmit={onReset}>
            <EmailField value={email} onChange={setEmail} />
            <CodeField value={code} onChange={setCode} />
            <PasswordField value={password} onChange={setPassword} autoComplete="new-password" label="Nieuw wachtwoord" />
            <p className="auth-hint">Minstens 12 tekens, met een hoofdletter, kleine letter, cijfer en symbool.</p>
            <button className="button button-primary" type="submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" /> : null}
              Wachtwoord instellen
            </button>
            <p className="auth-switch">
              <button type="button" className="auth-link" onClick={() => go("login")}>
                Terug naar aanmelden
              </button>
            </p>
          </form>
        ) : null}

        <p className="login-note">Veilig aangemeld via Amazon Cognito · je routes blijven privé</p>
      </section>
    </main>
  );
}

function EmailField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="auth-field">
      <span>E-mailadres</span>
      <input
        type="email"
        inputMode="email"
        autoComplete="email"
        required
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="jij@voorbeeld.be"
      />
    </label>
  );
}

function PasswordField({
  value,
  onChange,
  autoComplete,
  label = "Wachtwoord",
}: {
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  label?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <label className="auth-field">
      <span>{label}</span>
      <div className="auth-input-wrap">
        <input
          type={show ? "text" : "password"}
          autoComplete={autoComplete}
          required
          minLength={12}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="••••••••••••"
        />
        <button type="button" className="auth-reveal" onClick={() => setShow((prev) => !prev)}>
          {show ? "Verberg" : "Toon"}
        </button>
      </div>
    </label>
  );
}

function CodeField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="auth-field">
      <span>Code uit je mail</span>
      <input
        type="text"
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="123456"
      />
    </label>
  );
}
