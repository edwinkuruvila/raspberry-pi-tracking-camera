import { LockKeyhole } from "lucide-react";
import { useState, type FormEvent } from "react";

type LoginScreenProps = {
  onLogin: (password: string) => Promise<void>;
};

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await onLogin(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <h1 className="login-title">Camera Hub</h1>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <div className="login-form">
            {error ? (
              <div className="login-error">
                <LockKeyhole size={17} />
                {error}
              </div>
            ) : null}
            <label className="login-field">
              <span>Password</span>
              <input
                type="password"
                placeholder="Enter password"
                value={password}
                onChange={(event) => setPassword(event.currentTarget.value)}
                autoComplete="current-password"
                autoFocus
                required
                disabled={submitting}
              />
            </label>
            <button className="login-button" type="submit" disabled={submitting || password.length === 0}>
              {submitting ? "Opening…" : "Open camera"}
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
