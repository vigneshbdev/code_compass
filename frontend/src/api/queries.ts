// TanStack Query setup and hooks (task T027). Story hooks are added in later tasks.
import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  apiFetch,
  isInProgress,
  type Codebase,
  type Conversation,
  type ConversationSummary,
  type Health,
  type Overview,
} from "./client";

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiFetch<Health>("/health"),
    refetchInterval: 30_000,
  });
}

// ── Codebases (task T056) ─────────────────────────────────────────────────────────────────

const POLL_MS = 1000; // research R14: the UI polls progress once a second

export function useCodebases() {
  return useQuery({
    queryKey: ["codebases"],
    queryFn: async () => (await apiFetch<{ items: Codebase[] }>("/codebases")).items,
    refetchInterval: (query) =>
      query.state.data?.some((c) => isInProgress(c.status)) ? POLL_MS : false,
  });
}

export function useCodebase(id: string | null) {
  return useQuery({
    queryKey: ["codebase", id],
    queryFn: () => apiFetch<Codebase>(`/codebases/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data && isInProgress(query.state.data.status) ? POLL_MS : false),
  });
}

function useCodebaseMutation<TVars>(fn: (vars: TVars) => Promise<Codebase | void>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["codebases"] });
      void client.invalidateQueries({ queryKey: ["codebase"] });
    },
  });
}

export function useCreateFromGithub() {
  return useCodebaseMutation((url: string) =>
    apiFetch<Codebase>("/codebases/github", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  );
}

export function useCreateFromZip() {
  return useCodebaseMutation((file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<Codebase>("/codebases/zip", { method: "POST", body: form });
  });
}

export function useDeleteCodebase() {
  return useCodebaseMutation((id: string) => apiFetch<void>(`/codebases/${id}`, { method: "DELETE" }));
}

export function useReingest() {
  return useCodebaseMutation((id: string) => apiFetch<Codebase>(`/codebases/${id}/reingest`, { method: "POST" }));
}


// ── Conversations (task T144) and feedback (task T146) ────────────────────────────────────

export function useConversations(codebaseId: string | null) {
  return useQuery({
    queryKey: ["conversations", codebaseId],
    queryFn: async () =>
      (await apiFetch<{ items: ConversationSummary[] }>(`/codebases/${codebaseId}/conversations`)).items,
    enabled: codebaseId !== null,
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<Conversation>(`/conversations/${id}`),
    enabled: id !== null,
  });
}

export function useCreateConversation(codebaseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<ConversationSummary>(`/codebases/${codebaseId}/conversations`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["conversations", codebaseId] }),
  });
}

export function useFeedback(conversationId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ messageId, value }: { messageId: string; value: 1 | -1 | null }) =>
      apiFetch<void>(`/messages/${messageId}/feedback`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["conversation", conversationId] }),
  });
}


export function useOverview(codebaseId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["overview", codebaseId],
    queryFn: () => apiFetch<Overview>(`/codebases/${codebaseId}/overview`),
    enabled: codebaseId !== null && enabled,
    staleTime: Infinity,
  });
}
