/**
 * Thin fetch wrapper around the Khata REST API. Injects the bearer token,
 * sends/parses JSON, and turns non-2xx responses into a typed ApiError that
 * carries the server's `error` code (the API's convention, e.g.
 * "invalid_credentials", "unauthenticated").
 */
import { API_BASE } from '../config';
import { peekToken } from '../auth/session';

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, code?: string, detail?: string) {
    super(detail || code || `HTTP ${status}`);
    this.status = status;
    this.code = code;
  }
}

type Options = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  /** Token to use instead of the stored one (e.g. right after login). */
  token?: string | null;
};

export async function api<T = any>(path: string, opts: Options = {}): Promise<T> {
  const { method = 'GET', body, token } = opts;
  const auth = token !== undefined ? token : peekToken();

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) headers['Authorization'] = `Bearer ${auth}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) {
    throw new ApiError(res.status, data?.error, data?.detail);
  }
  return data as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
