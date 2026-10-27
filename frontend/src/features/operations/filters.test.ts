import { describe, expect, it } from "vitest";

import type { MapAgent, MapEquipment } from "@/lib/api/types";

import {
  activeFilterCount,
  EMPTY_FILTERS,
  filterAgents,
  filterEquipment,
  parseFilters,
  toSearchParams,
  toggle,
} from "./filters";

const base: MapEquipment = {
  id: "1",
  type_code: "camera",
  serial_number: "CAM-001",
  status: "operacional",
  lat: -22.2,
  lng: -49.9,
  region_id: "centro",
  organization_id: "gcm",
  neighborhood: "Fragata",
  maintenance_need: "nenhuma",
  next_maintenance_date: null,
  connectivity: "online",
  last_seen_at: null,
  open_alerts: 0,
  top_alert_severity: null,
};

const items: MapEquipment[] = [
  base,
  {
    ...base,
    id: "2",
    serial_number: "RAD-1",
    type_code: "radar",
    status: "mau_funcionamento",
    maintenance_need: "imediata",
    open_alerts: 1,
  },
  {
    ...base,
    id: "3",
    serial_number: "SEM-1",
    type_code: "semaforo",
    region_id: "norte",
    next_maintenance_date: "2026-10-20",
  },
  {
    ...base,
    id: "4",
    serial_number: "PAT-1",
    type_code: "patinete",
    connectivity: "offline",
    next_maintenance_date: "2026-10-30",
  },
];
const NOW = new Date("2026-10-26T12:00:00Z");
const ids = (list: MapEquipment[]) => list.map((i) => i.id);

describe("filterEquipment", () => {
  it("sem filtros devolve tudo", () => {
    expect(filterEquipment(items, EMPTY_FILTERS, NOW)).toHaveLength(4);
  });

  it("combina tipo e situação (E entre grupos, OU dentro do grupo)", () => {
    const filters = {
      ...EMPTY_FILTERS,
      types: ["radar", "camera"],
      statuses: ["mau_funcionamento" as const],
    };
    expect(ids(filterEquipment(items, filters, NOW))).toEqual(["2"]);
  });

  it("filtra manutenção vencida e próxima relativas a hoje", () => {
    expect(
      ids(filterEquipment(items, { ...EMPTY_FILTERS, maintenance: ["vencida"] }, NOW)),
    ).toEqual(["3"]);
    expect(
      ids(filterEquipment(items, { ...EMPTY_FILTERS, maintenance: ["proxima"] }, NOW)),
    ).toEqual(["4"]);
    expect(
      ids(filterEquipment(items, { ...EMPTY_FILTERS, maintenance: ["imediata"] }, NOW)),
    ).toEqual(["2"]);
  });

  it("busca por série ou bairro sem diferenciar maiúsculas", () => {
    expect(ids(filterEquipment(items, { ...EMPTY_FILTERS, search: "rad" }, NOW))).toEqual(["2"]);
    expect(filterEquipment(items, { ...EMPTY_FILTERS, search: "fragata" }, NOW)).toHaveLength(4);
  });

  it("filtra conectividade, região e somente com alerta", () => {
    expect(
      ids(filterEquipment(items, { ...EMPTY_FILTERS, connectivity: ["offline"] }, NOW)),
    ).toEqual(["4"]);
    expect(ids(filterEquipment(items, { ...EMPTY_FILTERS, regions: ["norte"] }, NOW))).toEqual([
      "3",
    ]);
    expect(ids(filterEquipment(items, { ...EMPTY_FILTERS, onlyAlerts: true }, NOW))).toEqual(["2"]);
  });
});

describe("filterAgents", () => {
  const agent = { id: "a", on_duty: true, region_id: "centro", organization_id: "gcm" } as MapAgent;
  it("esconde agentes fora de serviço por padrão", () => {
    const off = { ...agent, id: "b", on_duty: false };
    expect(filterAgents([agent, off], EMPTY_FILTERS).map((a) => a.id)).toEqual(["a"]);
    expect(filterAgents([agent, off], { ...EMPTY_FILTERS, onlyOnDuty: false })).toHaveLength(2);
  });
});

describe("URL", () => {
  it("serializa e lê de volta os mesmos filtros (visão compartilhável)", () => {
    const filters = {
      ...EMPTY_FILTERS,
      types: ["radar"],
      statuses: ["furtado" as const],
      onlyAlerts: true,
      search: "x",
      onlyOnDuty: false,
    };
    expect(parseFilters(toSearchParams(filters))).toEqual(filters);
    expect(activeFilterCount(filters)).toBe(4);
  });

  it("preserva parâmetros que não são de filtro", () => {
    const params = toSearchParams(EMPTY_FILTERS, new URLSearchParams("focus=1"));
    expect(params.get("focus")).toBe("1");
  });
});

describe("toggle", () => {
  it("adiciona e remove", () => {
    expect(toggle(["a"], "b")).toEqual(["a", "b"]);
    expect(toggle(["a", "b"], "a")).toEqual(["b"]);
  });
});
