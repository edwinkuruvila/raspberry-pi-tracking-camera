export const AUTH_REQUIRED_EVENT = "roomcam:auth-required";

export function notifyIfUnauthorized(response: Response): void {
  if (response.status === 401) {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    notifyIfUnauthorized(response);
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

export async function responseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    // Fall back to the HTTP status when the response has no JSON body.
  }
  return `${response.status} ${response.statusText}`;
}
