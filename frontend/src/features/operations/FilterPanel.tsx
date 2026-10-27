import { FilterX, Search } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Switch } from "@/components/ui/controls";
import { Input, Label } from "@/components/ui/primitives";
import type { Connectivity, EquipmentType, Organization, Region } from "@/lib/api/types";
import { EQUIPMENT_STATUS, STATUS_ORDER, typeIcon } from "@/lib/vocabulary";

import {
  activeFilterCount,
  EMPTY_FILTERS,
  toggle,
  type MaintenanceFilter,
  type MapFilters,
} from "./filters";

const MAINTENANCE: { value: MaintenanceFilter; label: string }[] = [
  { value: "imediata", label: "Reparo imediato" },
  { value: "vencida", label: "Vencida" },
  { value: "proxima", label: "Vence em 7 dias" },
];

const CONNECTIVITY: { value: Connectivity; label: string }[] = [
  { value: "online", label: "Online" },
  { value: "offline", label: "Sem comunicação" },
  { value: "sem_telemetria", label: "Sem telemetria" },
];

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-xs font-medium text-muted-foreground">{title}</legend>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </fieldset>
  );
}

export function FilterPanel({
  filters,
  onChange,
  types,
  regions,
  organizations,
  statusCounts,
  typeCounts,
}: {
  filters: MapFilters;
  onChange: (filters: MapFilters) => void;
  types: EquipmentType[];
  regions: Region[];
  organizations: Organization[];
  statusCounts: Record<string, number>;
  typeCounts: Record<string, number>;
}) {
  const set = <K extends keyof MapFilters>(key: K, value: MapFilters[K]) =>
    onChange({ ...filters, [key]: value });
  const active = activeFilterCount(filters);

  return (
    <div className="space-y-4 p-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            aria-label="Buscar por série ou bairro"
            placeholder="Série ou bairro…"
            className="pl-8"
            value={filters.search}
            onChange={(e) => set("search", e.target.value)}
          />
        </div>
        <Button
          variant="ghost"
          disabled={!active}
          onClick={() => onChange({ ...EMPTY_FILTERS, onlyOnDuty: filters.onlyOnDuty })}
        >
          <FilterX /> Limpar
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-lg border bg-background/30 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="only-alerts" className="text-xs text-foreground">
            Com alerta aberto
          </Label>
          <Switch
            id="only-alerts"
            checked={filters.onlyAlerts}
            onCheckedChange={(v) => set("onlyAlerts", v)}
          />
        </div>
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor="on-duty" className="text-xs text-foreground">
            Agentes em serviço
          </Label>
          <Switch
            id="on-duty"
            checked={filters.onlyOnDuty}
            onCheckedChange={(v) => set("onlyOnDuty", v)}
          />
        </div>
      </div>

      <Group title="Situação">
        {STATUS_ORDER.map((status) => {
          const visual = EQUIPMENT_STATUS[status];
          const Icon = visual.icon;
          return (
            <Chip
              key={status}
              pressed={filters.statuses.includes(status)}
              onToggle={() => set("statuses", toggle(filters.statuses, status))}
              count={statusCounts[status] ?? 0}
            >
              <Icon className="h-3.5 w-3.5" style={{ color: `hsl(${visual.color})` }} aria-hidden />
              {visual.label}
            </Chip>
          );
        })}
      </Group>

      <Group title="Manutenção">
        {MAINTENANCE.map((m) => (
          <Chip
            key={m.value}
            pressed={filters.maintenance.includes(m.value)}
            onToggle={() => set("maintenance", toggle(filters.maintenance, m.value))}
          >
            {m.label}
          </Chip>
        ))}
      </Group>

      <Group title="Comunicação">
        {CONNECTIVITY.map((c) => (
          <Chip
            key={c.value}
            pressed={filters.connectivity.includes(c.value)}
            onToggle={() => set("connectivity", toggle(filters.connectivity, c.value))}
          >
            {c.label}
          </Chip>
        ))}
      </Group>

      <Group title="Tipo de equipamento">
        {types.map((t) => {
          const Icon = typeIcon(t.code);
          return (
            <Chip
              key={t.code}
              pressed={filters.types.includes(t.code)}
              onToggle={() => set("types", toggle(filters.types, t.code))}
              count={typeCounts[t.code] ?? 0}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              {t.name}
            </Chip>
          );
        })}
      </Group>

      <Group title="Região">
        {regions.map((r) => (
          <Chip
            key={r.id}
            pressed={filters.regions.includes(r.id)}
            onToggle={() => set("regions", toggle(filters.regions, r.id))}
          >
            {r.name}
          </Chip>
        ))}
      </Group>

      <Group title="Órgão responsável">
        {organizations.map((o) => (
          <Chip
            key={o.id}
            title={o.name}
            pressed={filters.organizations.includes(o.id)}
            onToggle={() => set("organizations", toggle(filters.organizations, o.id))}
          >
            {o.acronym}
          </Chip>
        ))}
      </Group>
    </div>
  );
}
