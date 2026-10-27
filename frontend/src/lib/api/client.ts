// Cliente HTTP tipado: timeout, problem+json (RFC 9457) → ApiError e sessão expirada.
import { tokenStore } from "@/lib/auth-store";

const DEFAULT_TIMEOUT_MS = 15_000;

export interface FieldError {
  field: string | null;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly fieldErrors: FieldError[];
  readonly problem: Record<string, unknown>;

  constructor(status: number, problem: Record<string, unknown>) {
    super(String(problem.detail ?? problem.title ?? `Erro ${status}`));
    this.name = "ApiError";
    this.status = status;
    this.code = String(problem.code ?? `http_${status}`);
    this.fieldErrors = Array.isArray(problem.errors) ? (problem.errors as FieldError[]) : [];
    this.problem = problem;
  }

  /** Mensagem do primeiro erro de um campo (ex.: "address.cep"). */
  fieldMessage(field: string): string | undefined {
    return this.fieldErrors.find((e) => e.field === field || e.field?.endsWith(`.${field}`))
      ?.message;
  }
}

type Query = Record<string, string | number | boolean | string[] | null | undefined>;

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  form?: URLSearchParams;
  query?: Query;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.append(key, String(value));
  }
  const qs = params.toString();
  return `/api/v1${path}${qs ? `?${qs}` : ""}`;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  options.signal?.addEventListener("abort", () => controller.abort(), { once: true });

  const headers: Record<string, string> = { Accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  try {
    const response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body,
      signal: controller.signal,
    });
    if (response.status === 204) return undefined as T;
    const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    if (!response.ok) {
      if (response.status === 401 && token) tokenStore.expire();
      throw new ApiError(response.status, payload);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(0, { detail: "Tempo de resposta esgotado. Tente novamente." });
    }
    if (error instanceof TypeError) {
      throw new ApiError(0, { detail: "Sem conexão com o servidor." });
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Erro inesperado.";
}
