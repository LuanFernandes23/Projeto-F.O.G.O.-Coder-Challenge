import { describe, expect, it } from "vitest";

import type { MapAgent, MapFeatures } from "@/lib/api/types";

import { applyPositions, staleQueriesFor } from "./live-reducer";

const agent = (id: string, lat: number, lng: number) =>
  ({ id, lat, lng, live: false, last_position_at: null }) as unknown as MapAgent;

const snapshot = {
  generated_at: "",
  equipment: [],
  agents: [agent("a", 1, 1), agent("b", 2, 2)],
} as MapFeatures;

describe("applyPositions", () => {
  it("move só os agentes informados e marca como ao vivo", () => {
    const next = applyPositions(snapshot, [{ id: "a", lat: 5, lng: 6 }], "agora")!;
    expect(next.agents[0]).toMatchObject({ lat: 5, lng: 6, live: true, last_position_at: "agora" });
    expect(next.agents[1]).toBe(snapshot.agents[1]); // objeto preservado: React não re-renderiza
  });

  it("devolve o mesmo snapshot quando nada muda", () => {
    expect(applyPositions(snapshot, [{ id: "a", lat: 1, lng: 1 }], "agora")).toBe(snapshot);
    expect(applyPositions(snapshot, [], "agora")).toBe(snapshot);
    expect(applyPositions(undefined, [{ id: "a", lat: 1, lng: 1 }], "agora")).toBeUndefined();
  });
});

describe("staleQueriesFor", () => {
  it("mudança de situação atualiza mapa, KPIs, regiões, alertas e o detalhe", () => {
    const keys = staleQueriesFor({ type: "equipment.status_changed", data: { id: "eq1" } });
    expect(keys).toEqual(
      expect.arrayContaining([
        ["map-features"],
        ["overview"],
        ["regions-health"],
        ["alerts"],
        ["equipment", "eq1"],
      ]),
    );
  });

  it("ordem de manutenção atualiza as ordens daquele equipamento", () => {
    expect(
      staleQueriesFor({ type: "maintenance.order_changed", data: { equipment_id: "e" } }),
    ).toContainEqual(["equipment-orders", "e"]);
  });

  it("evento desconhecido não invalida nada", () => {
    expect(staleQueriesFor({ type: "outro", data: {} })).toEqual([]);
  });
});
