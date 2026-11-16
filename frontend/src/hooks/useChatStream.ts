// Streams one answer over SSE and exposes it while it arrives (FR-010, task T144).
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Message, MessageStatus } from "../api/client";
import { postSse } from "../api/sse";

export interface PendingAnswer {
  question: string;
  message: Message;
  error: string | null;
}

function draft(question: string): PendingAnswer {
  return {
    question,
    error: null,
    message: {
      id: "pending",
      seq: 0,
      role: "assistant",
      status: "complete",
      content: "",
      citations: [],
      trace_id: null,
      trace_url: null,
      feedback: null,
      usage: null,
      created_at: new Date().toISOString(),
    },
  };
}

export function useChatStream(conversationId: string | null, codebaseId: string) {
  const client = useQueryClient();
  const [pending, setPending] = useState<PendingAnswer | null>(null);

  const send = useCallback(
    async (question: string, targetId: string | null = conversationId) => {
      if (!targetId) return;
      setPending(draft(question));
      const update = (fn: (p: PendingAnswer) => PendingAnswer) => setPending((p) => (p ? fn(p) : p));
      try {
        await postSse(`/api/conversations/${targetId}/messages`, { content: question }, ({ event, data }) => {
          if (event === "meta")
            update((p) => ({ ...p, message: { ...p.message, trace_url: (data.trace_url as string) ?? null } }));
          if (event === "token")
            update((p) => ({ ...p, message: { ...p.message, content: p.message.content + String(data.text ?? "") } }));
          if (event === "done")
            update((p) => ({ ...p, message: { ...p.message, status: data.status as MessageStatus } }));
          if (event === "error") update((p) => ({ ...p, error: String(data.message ?? "The answer failed.") }));
        });
      } catch (err) {
        update((p) => ({ ...p, error: (err as Error).message }));
      } finally {
        await client.invalidateQueries({ queryKey: ["conversation", targetId] });
        await client.invalidateQueries({ queryKey: ["conversations", codebaseId] });
        setPending((p) => (p && !p.error ? null : p));
      }
    },
    [client, codebaseId, conversationId],
  );

  return { pending, send, clearError: () => setPending(null) };
}
