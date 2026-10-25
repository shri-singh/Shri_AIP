// Thin fetch wrapper for the revamp REST APIs (/api/v2/*). Same-origin through NGINX, so the
// browser never needs CORS. Plug Opsi's existing token getter in via `configureAuth` once at startup.

export type TokenGetter = () => Promise<string | null> | string | null;

let getToken: TokenGetter = () => null;

/** Call once (e.g. in the app shell) with the existing Opsi auth hook/service. */
export function configureAuth(getter: TokenGetter): void {
  getToken = getter;
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(await authHeaders())) headers.set(k, v);
  headers.set("x-request-id", crypto.randomUUID());
  if (init.body && !headers.has("content-type")) headers.set("content-type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}
