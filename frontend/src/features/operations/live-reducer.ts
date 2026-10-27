// Funções puras que aplicam eventos em tempo real ao snapshot do mapa (testadas).
import type { MapFeatures } from "@/lib/api/types";

export interface PositionUpdate {
  id: string;
  lat: number;
  lng: number;
}

export interface LiveEvent {
  type: string;
  data: Record<string, unknown>;
}

/** Atualiza só as posições recebidas; devolve o mesmo objeto se nada mudou. */
export function applyPositions(
  snapshot: MapFeatures | undefined,
  positions: PositionUpdate[],
  receivedAt: string,
): MapFeatures | undefined {
  if (!snapshot || positions.length === 0) return snapshot;
  const byId = new Map(positions.map((p) => [p.id, p]));
  let changed = false;
  const agents = snapshot.agents.map((agent) => {
    const update = byId.get(agent.id);
    if (!update || (update.lat === agent.lat && update.lng === agent.lng)) return agent;
    changed = true;
    return { ...agent, lat: update.lat, lng: update.lng, live: true, last_position_at: receivedAt };
  });
  return changed ? { ...snapshot, agents } : snapshot;
}

/** Quais consultas cada tipo de evento torna desatualizadas. */
export function staleQueriesFor(event: LiveEvent): string[][] {
  const equipmentId =
    typeof event.data.equipment_id === "string" ? event.data.equipment_id : undefined;
  const id = typeof event.data.id === "string" ? event.data.id : undefined;
  switch (event.type) {
    case "equipment.status_changed":
      return [
        ["map-features"],
        ["overview"],
        ["regions-health"],
        ["alerts"],
        ...(id ? [["equipment", id]] : []),
      ];
    case "equipment.connectivity":
      return [["map-features"], ["overview"]];
    case "alert.opened":
    case "alert.updated":
    case "alert.resolved":
      return [["alerts"], ["overview"], ["map-features"], ["regions-health"]];
    case "dispatch.updated":
      return [["dispatches"], ["map-features"], ["overview"]];
    case "agent.status_changed":
      return [["map-features"], ["overview"]];
    case "maintenance.order_changed":
      return [
        ["map-features"],
        ...(equipmentId
          ? [
              ["equipment-orders", equipmentId],
              ["equipment", equipmentId],
            ]
          : []),
      ];
    // Parte 3 — PROMETHEUS e Cidade Preditiva
    case "prometheus.decision":
      return [["prometheus"], ["map-features"], ["dispatches"]];
    case "fault.averted":
      return [["prometheus"], ["predictions"], ["map-features"]];
    case "prediction.updated":
      return [["predictions", "city"]];
    case "anomaly.detected":
      return [["predictions", "anomalies"]];
    default:
      return [];
  }
}
