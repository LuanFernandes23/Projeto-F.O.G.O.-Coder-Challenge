// Consultas da Cidade Preditiva e do PROMETHEUS (TanStack Query).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api/client";
import type { Decision, PrometheusStats } from "@/lib/api/types";

import type { AnomalySnapshot, CityForecast, Snapshot } from "./types";

const REFRESH_MS = 60_000;

export const useCityForecast = () =>
  useQuery({
    queryKey: ["predictions", "city"],
    queryFn: () => api<Snapshot<CityForecast>>("/predictions/city"),
    // Enquanto o primeiro ajuste não termina, consulta mais vezes.
    refetchInterval: (query) => (query.state.data?.ready ? REFRESH_MS * 5 : 10_000),
  });

export const useAnomalies = () =>
  useQuery({
    queryKey: ["predictions", "anomalies"],
    queryFn: () => api<Snapshot<AnomalySnapshot>>("/predictions/anomalies"),
    refetchInterval: REFRESH_MS,
  });

export function useRefreshPredictions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api<{ model_id: number | null; skill_vs_mean: number | null }>("/predictions/refresh", {
        method: "POST",
        timeoutMs: 120_000,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["predictions"] });
      toast.success("Modelos reajustados e previsões recalculadas");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export const useDecisions = (status?: string[]) =>
  useQuery({
    queryKey: ["prometheus", "decisions", status ?? "todas"],
    queryFn: () => api<Decision[]>("/prometheus/decisions", { query: { status, limit: 40 } }),
    refetchInterval: REFRESH_MS,
  });

export const usePrometheusStats = () =>
  useQuery({
    queryKey: ["prometheus", "stats"],
    queryFn: () => api<PrometheusStats>("/prometheus/stats", { query: { hours: 24 } }),
    refetchInterval: REFRESH_MS,
  });

export function useAnswerDecision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, note }: { id: string; approve: boolean; note?: string }) =>
      api<Decision>(`/prometheus/decisions/${id}/${approve ? "approve" : "reject"}`, {
        method: "POST",
        body: { note: note || null },
        timeoutMs: 60_000,
      }),
    onSuccess: (decision) => {
      void queryClient.invalidateQueries({ queryKey: ["prometheus"] });
      void queryClient.invalidateQueries({ queryKey: ["map-features"] });
      void queryClient.invalidateQueries({ queryKey: ["dispatches"] });
      if (decision.status === "executada") {
        toast.success("Ação aprovada e executada", {
          description: decision.result?.message as string | undefined,
        });
      } else if (decision.status === "rejeitada") {
        toast("Ação rejeitada", { description: decision.title });
      } else {
        toast.error("A ação aprovada não pôde ser executada", {
          description: decision.error ?? undefined,
        });
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function useOpenPreventiveOrder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ equipmentId, description }: { equipmentId: string; description: string }) =>
      api(`/equipment/${equipmentId}/maintenance-orders`, {
        method: "POST",
        // "agendada" exige data no servidor (422); antecipar é agir já, como faz o PROMETHEUS.
        body: { kind: "preventiva", priority: "imediata", description, scheduled_for: null },
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["map-features"] });
      toast.success("OS preventiva aberta");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}
