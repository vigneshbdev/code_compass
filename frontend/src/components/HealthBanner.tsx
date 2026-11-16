// NFR-007 health banner (task T029): blocking for LLM/database problems, a quiet warning
// when only tracing (Langfuse) is unavailable, nothing when all is well.
import type { Health } from "../api/client";

const BAD = new Set(["missing", "invalid", "unreachable"]);

export function isBlocking(health: Health): boolean {
  return BAD.has(health.llm) || BAD.has(health.database);
}

const LLM_TEXT: Record<string, string> = {
  missing: "No LLM API key is configured.",
  invalid: "The LLM API key was rejected by the provider.",
  unreachable: "The LLM provider cannot be reached.",
};

export function HealthBanner({ health }: { health: Health }) {
  if (isBlocking(health)) {
    return (
      <div
        role="alert"
        className="border-b border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
      >
        {BAD.has(health.llm) && (
          <p>
            <strong>{LLM_TEXT[health.llm]}</strong> Chat is unavailable until this is fixed.{" "}
            {health.llm_help_url ? (
              <a className="font-medium underline" href={health.llm_help_url} target="_blank" rel="noreferrer">
                How to get a free Gemini key
              </a>
            ) : (
              <span>See the README section “Get a free Gemini key”.</span>
            )}
          </p>
        )}
        {BAD.has(health.database) && (
          <p>
            <strong>The database is unreachable.</strong> Check that the postgres container is
            running.
          </p>
        )}
      </div>
    );
  }
  if (health.langfuse === "unreachable") {
    return (
      <div
        role="status"
        className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
      >
        Tracing is unavailable (Langfuse unreachable). Chat still works; traces for this period
        will be missing.
      </div>
    );
  }
  return null;
}
