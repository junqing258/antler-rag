import { authState } from "../composables/useAuth";

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = authState.token;
  if (token) headers.set("Authorization", `Bearer ${token}`);
  headers.set("x-request-id", crypto.randomUUID());
  headers.set("accept-language", navigator.language);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) authState.clear();
  if (response.status === 204) return undefined as T;
  const payload = await response.json();
  if (!response.ok) throw new ApiError(response.status, payload.code ?? "request_failed", payload.message ?? "Request failed");
  return payload as T;
}
