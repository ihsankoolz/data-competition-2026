/**
 * The only way the web app talks to the FastAPI backend.
 *
 * Types come from `schema.d.ts`, which `pnpm gen:api` generates from the
 * FastAPI OpenAPI spec. Never hand-write API types; regenerate instead.
 *
 * In the browser, requests go to `/api/*`, which Next rewrites to the API
 * origin (see next.config.ts), so there is no CORS. On the server they go
 * straight to `API_ORIGIN`.
 *
 * Usage:
 *   const clock = await api.GET("/clock");
 *   await api.POST("/clock/advance", { body: { days: 1 } });
 *   await api.GET("/requests/{id}", { path: { id } });   // path params
 */
import { getActingUserId } from "@/lib/acting-user";
import { reportApiOffline, reportApiOnline } from "@/lib/api/status";
import type { components, paths } from "@/lib/api/schema";

type HttpMethod = "get" | "post" | "put" | "patch" | "delete";

/** Paths that support the given HTTP method. */
export type PathsWithMethod<M extends HttpMethod> = {
  [P in keyof paths]: [NonNullable<paths[P][M]>] extends [never] ? never : P;
}[keyof paths];

type Operation<P extends keyof paths, M extends HttpMethod> = NonNullable<paths[P][M]>;

type JsonOf<T> = T extends { content: { "application/json": infer R } } ? R : undefined;

type SuccessStatus = 200 | 201 | 202 | 203 | 204;

/** The JSON body of an operation's success response. */
export type ResponseOf<O> = O extends { responses: infer R }
  ? JsonOf<R[Extract<keyof R, SuccessStatus>]>
  : never;

type ParamsOf<O> = O extends { parameters: infer Prm } ? Prm : never;
type PathParamsOf<O> = NonNullable<ParamsOf<O> extends { path?: infer X } ? X : never>;
type QueryOf<O> = NonNullable<ParamsOf<O> extends { query?: infer X } ? X : never>;
type BodyOf<O> = O extends { requestBody?: infer B } ? JsonOf<NonNullable<B>> : never;

type BodyOption<O> = [BodyOf<O>] extends [never]
  ? { body?: never }
  : O extends { requestBody: unknown }
    ? { body: BodyOf<O> }
    : { body?: BodyOf<O> };

type PathOption<O> = [PathParamsOf<O>] extends [never]
  ? { path?: never }
  : { path: PathParamsOf<O> };

type QueryOption<O> = [QueryOf<O>] extends [never]
  ? { query?: never }
  : ParamsOf<O> extends { query: unknown }
    ? { query: QueryOf<O> }
    : { query?: QueryOf<O> };

export type RequestOptions<O> = BodyOption<O> &
  PathOption<O> &
  QueryOption<O> & {
    signal?: AbortSignal;
    /** Override the persona sent in X-Acting-User (defaults to the header switcher). */
    actingUser?: string | null;
  };

type Args<O> =
  Partial<RequestOptions<O>> extends RequestOptions<O>
    ? [options?: RequestOptions<O>]
    : [options: RequestOptions<O>];

/** A failed API call. `offline` means the server could not be reached at all. */
export class ApiError extends Error {
  readonly status: number;
  readonly offline: boolean;
  readonly detail: unknown;
  /** The whole JSON error body, e.g. submit's 422 `{detail, issues}`. */
  readonly body: unknown;

  constructor(
    message: string,
    opts: { status: number; offline?: boolean; detail?: unknown; body?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status;
    this.offline = opts.offline ?? false;
    this.detail = opts.detail;
    this.body = opts.body;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

function baseUrl(): string {
  if (typeof window !== "undefined") return "/api";
  return process.env.API_ORIGIN ?? "http://localhost:8000";
}

/** The full URL for an API path template, e.g. `/emails/{email_id}`. */
export function buildUrl(
  template: string,
  path?: Record<string, unknown>,
  query?: Record<string, unknown>,
): string {
  let url = template.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = path?.[name];
    if (value === undefined || value === null) {
      throw new Error(`Missing path parameter "${name}" for ${template}`);
    }
    return encodeURIComponent(String(value));
  });
  if (query) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      if (Array.isArray(value)) {
        for (const v of value) search.append(key, String(v));
      } else {
        search.append(key, String(value));
      }
    }
    const qs = search.toString();
    if (qs) url += `?${qs}`;
  }
  return baseUrl() + url;
}

/** Turns FastAPI's `detail` (string or validation list) into one readable line. */
function describeDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown };
    const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
    if (typeof first.msg === "string") {
      return field ? `${String(field)}: ${first.msg}` : first.msg;
    }
  }
  return `The server could not complete this request (error ${status}).`;
}

const OFFLINE_MESSAGE = "Can't reach the demo server.";
const RETRY_AFTER_MS = 300;

/** The headers every call sends; `X-Acting-User` is the header switcher's persona. */
export function baseHeaders(actingUser?: string | null): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const who = actingUser === undefined ? getActingUserId() : actingUser;
  if (who) headers["X-Acting-User"] = who;
  return headers;
}

async function request(
  method: HttpMethod,
  pathTemplate: string,
  options: {
    body?: unknown;
    path?: Record<string, unknown>;
    query?: Record<string, unknown>;
    signal?: AbortSignal;
    actingUser?: string | null;
  } = {},
): Promise<unknown> {
  const url = buildUrl(pathTemplate, options.path, options.query);
  const headers = baseHeaders(options.actingUser);
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  // A GET is safe to repeat, so one dropped connection (the proxy's "socket hang up", D-025) is
  // retried once before the header says the server is offline. Writes are never repeated.
  const attempts = method === "get" ? 2 : 1;
  let res: Response | null = null;
  for (let attempt = 1; ; attempt++) {
    try {
      res = await fetch(url, {
        method: method.toUpperCase(),
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
        cache: "no-store",
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      res = null;
    }
    // The Next proxy answers 5xx without a JSON body when the API is down.
    const reached =
      res !== null &&
      (res.status < 500 || !!res.headers.get("content-type")?.includes("application/json"));
    if (reached || attempt >= attempts) break;
    await new Promise((resolve) => setTimeout(resolve, RETRY_AFTER_MS));
    options.signal?.throwIfAborted();
  }

  if (res === null) {
    reportApiOffline();
    throw new ApiError(OFFLINE_MESSAGE, { status: 0, offline: true });
  }

  const isJson = res.headers.get("content-type")?.includes("application/json");

  if (!isJson && res.status >= 500) {
    reportApiOffline();
    throw new ApiError(OFFLINE_MESSAGE, { status: res.status, offline: true });
  }
  reportApiOnline();

  const payload: unknown = res.status === 204 || !isJson ? undefined : await res.json();

  if (!res.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(describeDetail(detail, res.status), {
      status: res.status,
      detail,
      body: payload,
    });
  }
  return payload;
}

function method<M extends HttpMethod>(m: M) {
  return <P extends PathsWithMethod<M>>(
    path: P,
    ...args: Args<Operation<P, M>>
  ): Promise<ResponseOf<Operation<P, M>>> =>
    request(m, path as string, args[0] as Parameters<typeof request>[2]) as Promise<
      ResponseOf<Operation<P, M>>
    >;
}

export const api = {
  GET: method("get"),
  POST: method("post"),
  PUT: method("put"),
  PATCH: method("patch"),
  DELETE: method("delete"),
};

/**
 * The field problems in an error body (submit's 422 is `{detail, issues}`, D-018 #3).
 * Anything that does not look like a FieldIssue is ignored.
 */
export function issuesOf(e: unknown): components["schemas"]["FieldIssue"][] {
  if (!isApiError(e) || !e.body || typeof e.body !== "object" || !("issues" in e.body)) return [];
  const raw = (e.body as { issues: unknown }).issues;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (i): i is components["schemas"]["FieldIssue"] =>
      !!i &&
      typeof i === "object" &&
      typeof (i as { field?: unknown }).field === "string" &&
      typeof (i as { message?: unknown }).message === "string",
  );
}

/** Shorthand for a schema type, e.g. `Schema<"Persona">`. */
export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];
