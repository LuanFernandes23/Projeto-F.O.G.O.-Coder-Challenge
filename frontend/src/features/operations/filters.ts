// Filtros do mapa: lógica pura (testada) + serialização na URL (visões compartilháveis).
import dayjs from "dayjs";

import type { Connectivity, EquipmentStatus, MapAgent, MapEquipment } from "@/lib/api/types";

export type MaintenanceFilter = "imediata" | "proxima" | "vencida";

export interface MapFilters {
  types: string[];
  statuses: EquipmentStatus[];
  regions: string[];
  organizations: string[];
  maintenance: MaintenanceFilter[];
  connectivity: Connectivity[];
  onlyAlerts: boolean;
  search: string;
  onlyOnDuty: boolean;
}

export const EMPTY_FILTERS: MapFilters = {
  types: [],
  statuses: [],
  regions: [],
  organizations: [],
  maintenance: [],
  connectivity: [],
  onlyAlerts: false,
  search: "",
  onlyOnDuty: true,
};

const LIST_KEYS = [
  "types",
  "statuses",
  "regions",
  "organizations",
  "maintenance",
  "connectivity",
] as const;

export function parseFilters(params: URLSearchParams): MapFilters {
  const list = (key: string) => params.get(key)?.split(",").filter(Boolean) ?? [];
  return {
    types: list("types"),
    statuses: list("statuses") as EquipmentStatus[],
    regions: list("regions"),
    organizations: list("organizations"),
    maintenance: list("maintenance") as MaintenanceFilter[],
    connectivity: list("connectivity") as Connectivity[],
    onlyAlerts: params.get("alerts") === "1",
    search: params.get("q") ?? "",
    onlyOnDuty: params.get("agents") !== "todos",
  };
}

export function toSearchParams(filters: MapFilters, base?: URLSearchParams): URLSearchParams {
  const params = new URLSearchParams(base);
  LIST_KEYS.forEach((key) => {
    const values = filters[key];
    if (values.length) params.set(key, values.join(","));
    else params.delete(key);
  });
  if (filters.onlyAlerts) params.set("alerts", "1");
  else params.delete("alerts");
  if (filters.search) params.set("q", filters.search);
  else params.delete("q");
  if (!filters.onlyOnDuty) params.set("agents", "todos");
  else params.delete("agents");
  return params;
}

export function activeFilterCount(filters: MapFilters): number {
  return (
    LIST_KEYS.reduce((n, key) => n + filters[key].length, 0) +
    (filters.onlyAlerts ? 1 : 0) +
    (filters.search ? 1 : 0)
  );
}

function maintenanceMatches(
  item: MapEquipment,
  wanted: MaintenanceFilter[],
  today: dayjs.Dayjs,
): boolean {
  if (!wanted.length) return true;
  const next = item.next_maintenance_date ? dayjs(item.next_maintenance_date) : undefined;
  return wanted.some((kind) => {
    if (kind === "imediata") return item.maintenance_need === "imediata";
    if (!next) return false;
    if (kind === "vencida") return next.isBefore(today, "day");
    return !next.isBefore(today, "day") && !next.isAfter(today.add(7, "day"), "day");
  });
}

export function filterEquipment(
  items: MapEquipment[],
  filters: MapFilters,
  now = new Date(),
): MapEquipment[] {
  const today = dayjs(now);
  const search = filters.search.trim().toLowerCase();
  return items.filter(
    (item) =>
      (!filters.types.length || filters.types.includes(item.type_code)) &&
      (!filters.statuses.length || filters.statuses.includes(item.status)) &&
      (!filters.regions.length ||
        (item.region_id !== null && filters.regions.includes(item.region_id))) &&
      (!filters.organizations.length || filters.organizations.includes(item.organization_id)) &&
      (!filters.connectivity.length || filters.connectivity.includes(item.connectivity)) &&
      (!filters.onlyAlerts || item.open_alerts > 0) &&
      maintenanceMatches(item, filters.maintenance, today) &&
      (!search ||
        item.serial_number.toLowerCase().includes(search) ||
        item.neighborhood.toLowerCase().includes(search)),
  );
}

export function filterAgents(items: MapAgent[], filters: MapFilters): MapAgent[] {
  return items.filter(
    (agent) =>
      (!filters.onlyOnDuty || agent.on_duty) &&
      (!filters.regions.length ||
        (agent.region_id !== null && filters.regions.includes(agent.region_id))) &&
      (!filters.organizations.length || filters.organizations.includes(agent.organization_id)),
  );
}

export function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}
