/**
 * The only place that talks HTTP. Every call goes to the ConceptTrail API (never to a database,
 * Redis or a model server). Errors are normalised into `ApiError` using the backend envelope
 * `{"error": {"code", "message", "request_id"}}` so screens can branch on `code`.
 */

export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8020/api/v1'
).replace(/\/$/, '');

const SESSION_KEY = 'concepttrail.session';
export const UNAUTHORIZED_EVENT = 'concepttrail:unauthorized';

export interface StoredSession {
  token: string;
  expiresAt: number; // epoch ms
}

/** Tokens live in sessionStorage (cleared with the tab), never in a URL or localStorage. */
export const session = {
  read(): StoredSession | null {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      const value = JSON.parse(raw) as StoredSession;
      if (!value.token || Date.now() >= value.expiresAt) {
        sessionStorage.removeItem(SESSION_KEY);
        return null;
      }
      return value;
    } catch {
      return null;
    }
  },
  write(token: string, expiresInSeconds: number) {
    try {
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({ token, expiresAt: Date.now() + expiresInSeconds * 1000 })
      );
    } catch {
      // storage can be unavailable (private mode); the session then lasts for this page only
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch {
      // ignore
    }
  },
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly retryAfter?: number;

  constructor(status: number, code: string, message: string, requestId?: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
  }

  get isFeatureDisabled() {
    return this.status === 503 && this.code === 'feature_not_enabled';
  }
  get isNetwork() {
    return this.status === 0;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  timeoutMs?: number;
  /** Login must not trigger the global "session expired" handling. */
  anonymous?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, timeoutMs = 20000, anonymous = false } = options;
  const url = new URL(API_BASE_URL + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const current = anonymous ? null : session.read();
  if (current) headers.Authorization = `Bearer ${current.token}`;

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    const timedOut = (err as Error)?.name === 'AbortError';
    throw new ApiError(
      0,
      timedOut ? 'request_timeout' : 'network_error',
      timedOut
        ? 'The server took too long to answer. Please try again.'
        : 'ConceptTrail could not reach the server. Check that the backend is running.'
    );
  } finally {
    window.clearTimeout(timer);
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const envelope = (payload as { error?: { code?: string; message?: string; request_id?: string } })?.error;
    const retry = Number(response.headers.get('Retry-After')) || undefined;
    const error = new ApiError(
      response.status,
      envelope?.code ?? `http_${response.status}`,
      envelope?.message ?? 'Something went wrong. Please try again.',
      envelope?.request_id ?? response.headers.get('X-Request-ID') ?? undefined,
      retry
    );
    if (response.status === 401 && !anonymous) {
      session.clear();
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw error;
  }
  return payload as T;
}
