/**
 * API client. Same-origin, cookie session; state-changing calls echo the CSRF
 * cookie in X-CSRF-Token (ADR-0004). Business rules live in the backend only.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public incident?: string,
  ) {
    super(message);
  }
}

import { noteGatewayHeaders } from "./gateway";

const BASE = "/api/v1";

function readCookie(name: string): string | null {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

type Options = {
  body?: unknown;
  idempotencyKey?: string;
  version?: string;
  signal?: AbortSignal;
};

async function request<T>(method: string, path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const csrf = readCookie("nextcam_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;
  if (opts.version) headers["If-Match"] = opts.version;

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    });
  } catch {
    throw new ApiError(0, "network_error", "ارتباط با سرور برقرار نشد");
  }

  noteGatewayHeaders(res.headers);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401) window.dispatchEvent(new CustomEvent("nextcam:unauthorized"));
    throw new ApiError(
      res.status,
      err.code ?? "error",
      err.message || "خطای ناشناخته",
      err.details,
      err.incident,
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, { signal }),
  post: <T>(path: string, body?: unknown, opts: Omit<Options, "body"> = {}) =>
    request<T>("POST", path, { ...opts, body }),
  patch: <T>(path: string, body: unknown, version: string) =>
    request<T>("PATCH", path, { body, version }),
  put: <T>(path: string, body: unknown, version: string) =>
    request<T>("PUT", path, { body, version }),
  del: <T>(path: string, version: string) => request<T>("DELETE", path, { version }),
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

/** Multipart upload of one file (Excel imports); same CSRF and error handling as JSON calls. */
export async function upload<T>(
  path: string,
  file: File,
  extra: Record<string, string> = {},
  idempotencyKey?: string,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  const headers: Record<string, string> = {};
  const csrf = readCookie("nextcam_csrf");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "network_error", "ارتباط با سرور برقرار نشد");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? "error", err.message || "خطای ناشناخته", err.details, err.incident);
  }
  return data as T;
}
