// Typed fetch wrapper (task T027). Parses the contract error shape into ApiError.

export type ApiErrorCode = string;

export class ApiError extends Error {
  constructor(
    public readonly code: ApiErrorCode,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorBody {
  error?: { code?: string; message?: string };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let body: ErrorBody = {};
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      // non-JSON error body: fall through to a generic message
    }
    throw new ApiError(
      body.error?.code ?? "http_error",
      body.error?.message ?? `Request failed (${response.status})`,
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface Health {
  status: "ok" | "degraded";
  llm: "ok" | "missing" | "invalid" | "unreachable";
  database: "ok" | "unreachable";
  langfuse: "ok" | "unreachable" | "disabled";
  llm_help_url: string;
  langfuse_ui_url: string;
  version: string;
}
