import { getJson, notifyIfUnauthorized } from "./client";

export type AuthStatus = { authenticated: boolean };

export function getAuthStatus(): Promise<AuthStatus> {
  return getJson<AuthStatus>("/api/auth/status");
}

export async function login(password: string): Promise<void> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (response.ok) return;
  if (response.status === 429) throw new Error("Too many attempts. Wait a few minutes and try again.");
  if (response.status === 401) throw new Error("That password is not correct.");
  throw new Error("Unable to sign in. Please try again.");
}

export async function logout(): Promise<void> {
  const response = await fetch("/api/auth/logout", { method: "POST" });
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(`${response.status} ${response.statusText}`);
  }
}
