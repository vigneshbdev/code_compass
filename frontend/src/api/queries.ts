// TanStack Query setup and hooks (task T027). Story hooks are added in later tasks.
import { QueryClient, useQuery } from "@tanstack/react-query";
import { apiFetch, type Health } from "./client";

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
