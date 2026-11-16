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

// ── Codebases (contracts/http-api.md "Codebases") ─────────────────────────────────────────

export type CodebaseStatus = "queued" | "ingesting" | "ready" | "failed";

export interface Progress {
  stage: string;
  files_done: number;
  files_total: number;
  chunks_done: number;
  chunks_total: number;
}

export interface Summary {
  indexed: number;
  skipped: { path: string; reason: string }[];
  skipped_by_reason: Record<string, number>;
  bytes_indexed: number;
}

export interface Codebase {
  id: string;
  name: string;
  source_type: "github" | "zip";
  source_url: string | null;
  source_ref: string | null;
  commit_sha: string | null;
  status: CodebaseStatus;
  error: string | null;
  error_code: string | null;
  reingest_required: boolean;
  progress: Progress | null;
  summary: Summary | null;
  created_at: string;
  updated_at: string;
}

export function isInProgress(status: CodebaseStatus): boolean {
  return status === "queued" || status === "ingesting";
}

// ── Conversations and chat (contracts/http-api.md "Conversations", "Chat") ────────────────

export interface CitationRef {
  path: string;
  start_line: number;
  end_line: number;
}

export type MessageStatus = "complete" | "error" | "declined" | "not_found" | "unverified";

export interface Message {
  id: string;
  seq: number;
  role: "user" | "assistant";
  status: MessageStatus;
  content: string;
  citations: CitationRef[];
  trace_id: string | null;
  trace_url: string | null;
  feedback: 1 | -1 | null;
  usage: Record<string, unknown> | null;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Conversation {
  id: string;
  codebase_id: string;
  title: string;
  messages: Message[];
}

export interface FileContent {
  path: string;
  language: string;
  line_count: number;
  content: string;
  redaction_count: number;
}

// ── Overview (FR-020, FR-021) ─────────────────────────────────────────────────────────────

export interface Overview {
  languages: { language: string; files: number; lines: number }[];
  dependencies: { manifest: string; ecosystem: string; name: string; spec: string; dev: boolean }[];
  starter_questions: string[];
  starter_source: "llm" | "template";
}
