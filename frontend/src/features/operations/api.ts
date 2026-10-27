// Consultas e comandos da Central de Operações (TanStack Query).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  Alert,
  AlertSeverity,
  AlertStatus,
  Dispatch,
  DispatchStatus,
  DispatchSuggestion,
  Equipment,
  EquipmentStatus,
  EquipmentType,
  HeatPoint,
  MaintenanceOrder,
  MapFeatures,
  OrganizationListItem,
  Overview,
  Page,
  Region,
  RegionHealth,
  StatusChange,
  StatusOption,
  TrendPoint,
} from "@/lib/api/types";

const LIVE_FALLBACK_MS = 60_000; // se o SSE cair, ainda atualiza a cada minuto

export const useOverview = () =>
  useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/operations/overview"),
    refetchInterval: LIVE_FALLBACK_MS,
  });

export const useMapFeatures = () =>
  useQuery({
    queryKey: ["map-features"],
    queryFn: () => api<MapFeatures>("/operations/map-features"),
    refetchInterval: LIVE_FALLBACK_MS,
  });

export const useRegionsHealth = () =>
  useQuery({
    queryKey: ["regions-health"],
    queryFn: () => api<RegionHealth[]>("/operations/regions"),
    refetchInterval: LIVE_FALLBACK_MS,
  });

export const useRegionShapes = () =>
  useQuery({
    queryKey: ["regions-geo"],
    queryFn: () => api<Region[]>("/regions", { query: { include_geometry: true } }),
    staleTime: Infinity,
  });

export const useHeatmap = (kind: "falhas" | "furtos", days: number, enabled: boolean) =>
  useQuery({
    queryKey: ["heatmap", kind, days],
    queryFn: () => api<HeatPoint[]>("/operations/heatmap", { query: { kind, days } }),
    enabled,
    staleTime: 5 * 60_000,
  });

export const useTrends = (days: number) =>
  useQuery({
    queryKey: ["trends", days],
    queryFn: () => api<TrendPoint[]>("/operations/trends", { query: { days } }),
    staleTime: 5 * 60_000,
  });

export interface AlertQuery {
  status?: AlertStatus[];
  severity?: AlertSeverity[];
  equipmentId?: string;
  limit?: number;
  offset?: number;
}

export const useAlerts = (query: AlertQuery) =>
  useQuery({
    queryKey: ["alerts", query],
    queryFn: () =>
      api<Page<Alert>>("/alerts", {
        query: {
          status: query.status,
          severity: query.severity,
          equipment_id: query.equipmentId,
          limit: query.limit ?? 100,
          offset: query.offset ?? 0,
        },
      }),
    placeholderData: keepPreviousData,
    refetchInterval: LIVE_FALLBACK_MS,
  });

export const useDispatches = () =>
  useQuery({
    queryKey: ["dispatches"],
    queryFn: () => api<Dispatch[]>("/dispatches", { query: { active: true } }),
  });

export const useEquipmentTypes = () =>
  useQuery({
    queryKey: ["equipment-types"],
    queryFn: () => api<EquipmentType[]>("/equipment-types"),
    staleTime: Infinity,
  });

export const useOrganizations = () =>
  useQuery({
    queryKey: ["organizations"],
    queryFn: () => api<OrganizationListItem[]>("/organizations"),
    staleTime: 10 * 60_000,
  });

export const useStatusCatalog = () =>
  useQuery({
    queryKey: ["equipment-statuses"],
    queryFn: () => api<StatusOption[]>("/equipment-statuses"),
    staleTime: Infinity,
  });

export const useEquipment = (id: string | undefined) =>
  useQuery({
    queryKey: ["equipment", id],
    queryFn: () => api<Equipment>(`/equipment/${id}`),
    enabled: Boolean(id),
  });

export const useEquipmentHistory = (id: string | undefined) =>
  useQuery({
    queryKey: ["equipment", id, "history"],
    queryFn: () =>
      api<Page<StatusChange>>(`/equipment/${id}/status-history`, { query: { limit: 8 } }),
    enabled: Boolean(id),
  });

export const useEquipmentOrders = (id: string | undefined) =>
  useQuery({
    queryKey: ["equipment-orders", id],
    queryFn: () =>
      api<Page<MaintenanceOrder>>(`/equipment/${id}/maintenance-orders`, { query: { limit: 5 } }),
    enabled: Boolean(id),
  });

export const useDispatchSuggestions = (equipmentId: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: ["dispatch-suggestions", equipmentId],
    queryFn: () =>
      api<DispatchSuggestion[]>("/operations/dispatch-suggestions", {
        query: { equipment_id: equipmentId },
      }),
    enabled: Boolean(equipmentId) && enabled,
    staleTime: 0,
  });

function useInvalidate() {
  const client = useQueryClient();
  return (...keys: unknown[][]) =>
    keys.forEach((queryKey) => void client.invalidateQueries({ queryKey }));
}

export function useChangeEquipmentStatus(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { to_status: EquipmentStatus; reason: string }) =>
      api<Equipment>(`/equipment/${id}/status-changes`, { method: "POST", body }),
    onSuccess: () =>
      invalidate(["equipment", id], ["equipment-orders", id], ["map-features"], ["overview"]),
  });
}

export function useTransitionOrder(equipmentId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({
      orderId,
      status,
    }: {
      orderId: string;
      status: "em_andamento" | "concluida" | "cancelada";
    }) =>
      api<MaintenanceOrder>(`/maintenance-orders/${orderId}`, {
        method: "PATCH",
        body: { status },
      }),
    onSuccess: () =>
      invalidate(
        ["equipment", equipmentId],
        ["equipment-orders", equipmentId],
        ["map-features"],
        ["overview"],
      ),
  });
}

export function useAcknowledgeAlert() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (alertId: string) =>
      api<Alert>(`/alerts/${alertId}/acknowledge`, { method: "POST" }),
    onSuccess: () => invalidate(["alerts"], ["overview"]),
  });
}

export function useCreateDispatch() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (body: { equipment_id: string; agent_id: string; notes?: string }) =>
      api<Dispatch>("/dispatches", { method: "POST", body }),
    onSuccess: () => invalidate(["dispatches"], ["map-features"], ["alerts"], ["overview"]),
  });
}

export function useTransitionDispatch() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: DispatchStatus }) =>
      api<Dispatch>(`/dispatches/${id}`, { method: "PATCH", body: { status } }),
    onSuccess: () => invalidate(["dispatches"], ["map-features"], ["overview"]),
  });
}
