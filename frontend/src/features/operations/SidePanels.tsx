import { MapPin, Navigation, Timer } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { ToneBar, ToneCard, toneStyle, type Tone } from "@/components/ui/tone";
import { errorMessage } from "@/lib/api/client";
import type { Dispatch, Overview, RegionHealth } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatDistance, formatPercent, fromNow } from "@/lib/format";
import { cn } from "@/lib/utils";
import { EQUIPMENT_STATUS, HEALTH, ROLE } from "@/lib/vocabulary";

import { useDispatches, useTransitionDispatch, useTrends } from "./api";

const LEVEL_TONE: Record<RegionHealth["level"], Tone> = {
  normal: "ok",
  atencao: "warn",
  critico: "bad",
};

/** Motivos sem repetir a disponibilidade, que já aparece na linha de métricas. */
const reasons = (region: RegionHealth) =>
  region.reasons.filter((reason) => !reason.startsWith("Disponibilidade"));

export function RegionRanking({
  regions,
  onSelect,
}: {
  regions: RegionHealth[] | undefined;
  onSelect: (region: RegionHealth) => void;
}) {
  if (!regions) return <Skeleton className="m-3 h-64" />;
  return (
    <ol className="space-y-2 p-3" aria-label="Regiões, da pior para a melhor">
      {regions.map((region) => (
        <li key={region.region_id}>
          <button
            type="button"
            onClick={() => onSelect(region)}
            className={cn(
              "tone-card w-full px-3 py-2.5 text-left",
              region.level !== "normal" && "tone-card--glow",
            )}
            style={toneStyle(LEVEL_TONE[region.level])}
            aria-label={`${region.name}: saúde ${region.score.toFixed(0)}, ${HEALTH[region.level].label}. Filtrar mapa pela região`}
          >
            <div className="flex items-baseline gap-2">
              <span className="truncate font-medium">{region.name}</span>
              <span className="text-[11px] font-semibold text-[hsl(var(--tone))]">
                {HEALTH[region.level].label}
              </span>
              <span className="ml-auto text-lg tabular-nums font-semibold leading-none text-[hsl(var(--tone))]">
                {region.score.toFixed(0)}
              </span>
            </div>
            <div className="mt-2">
              <ToneBar value={region.score} />
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              Disponibilidade {formatPercent(region.availability_pct, 0)} · {region.unavailable}{" "}
              fora · {region.agents_on_duty} agentes
            </p>
            {reasons(region).length > 0 && (
              <p className="mt-0.5 line-clamp-2 text-[11px] text-foreground/80">
                {reasons(region).slice(0, 2).join(" · ")}
              </p>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}

export function DispatchList({ onLocate }: { onLocate: (dispatch: Dispatch) => void }) {
  const dispatches = useDispatches();
  const transition = useTransitionDispatch();
  const { can } = useAuth();
  if (dispatches.isLoading) return <Skeleton className="m-3 h-40" />;
  const items = dispatches.data ?? [];
  if (!items.length) {
    return (
      <p className="p-6 text-center text-sm text-muted-foreground">
        Nenhuma equipe despachada no momento.
      </p>
    );
  }
  return (
    <ul className="space-y-2 p-3">
      {items.map((d) => (
        <ToneCard
          as="li"
          key={d.id}
          tone={d.status === "no_local" ? "ok" : "info"}
          glow={false}
          className="px-3 py-2.5 text-sm"
        >
          <div className="flex items-baseline gap-2">
            <span className="truncate font-medium">{d.agent_name}</span>
            <span className="ml-auto shrink-0 text-[11px] font-semibold text-[hsl(var(--tone))]">
              {d.status_label}
            </span>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {ROLE[d.agent_role].short} · {d.organization_acronym} → {d.equipment_serial}
          </p>
          <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Navigation className="h-3 w-3" aria-hidden /> {formatDistance(d.distance_m)}
            </span>
            <span className="inline-flex items-center gap-1">
              <Timer className="h-3 w-3" aria-hidden /> {Math.round(d.eta_minutes)} min
            </span>
            <span className="truncate">{fromNow(d.created_at)}</span>
            <span className="ml-auto flex shrink-0 gap-1">
              <Button size="xs" variant="ghost" onClick={() => onLocate(d)}>
                <MapPin /> Mapa
              </Button>
              {can("dispatch:manage") && d.status === "no_local" && (
                <Button
                  size="xs"
                  onClick={() =>
                    transition.mutate(
                      { id: d.id, status: "concluido" },
                      {
                        onSuccess: () => toast.success("Atendimento concluído"),
                        onError: (e) => toast.error(errorMessage(e)),
                      },
                    )
                  }
                >
                  Concluir
                </Button>
              )}
              {can("dispatch:manage") && (
                <Button
                  size="xs"
                  variant="ghost"
                  className="text-muted-foreground"
                  onClick={() =>
                    transition.mutate(
                      { id: d.id, status: "cancelado" },
                      {
                        onSuccess: () => toast("Despacho cancelado"),
                        onError: (e) => toast.error(errorMessage(e)),
                      },
                    )
                  }
                >
                  Cancelar
                </Button>
              )}
            </span>
          </div>
        </ToneCard>
      ))}
    </ul>
  );
}

export function Insights({ overview }: { overview: Overview | undefined }) {
  const trends = useTrends(14);
  const data = (trends.data ?? []).map((p) => ({
    dia: p.day.slice(8, 10) + "/" + p.day.slice(5, 7),
    Falhas: p.failures,
    Reparos: p.repairs,
    MTTR: p.mttr_hours ?? undefined,
  }));
  const byType = (overview?.by_type ?? []).slice(0, 8).map((t) => ({
    tipo: t.type_name.split(" ")[0],
    Operacionais: t.operational,
    Indisponíveis: t.unavailable,
  }));
  const axis = { fontSize: 11, fill: "hsl(var(--muted-foreground))" };
  const tooltip = {
    contentStyle: {
      background: "hsl(var(--popover))",
      border: "1px solid hsl(var(--border))",
      borderRadius: 8,
      fontSize: 12,
    },
  };
  return (
    <div className="space-y-5 p-3">
      <section aria-label="Falhas e reparos dos últimos 14 dias">
        <h3 className="mb-0.5 text-sm font-medium">Falhas × reparos (14 dias)</h3>
        <p className="mb-2 text-[11px] text-muted-foreground">
          Linha: tempo médio de reparo (horas)
        </p>
        {trends.isLoading ? (
          <Skeleton className="h-48" />
        ) : (
          <div className="h-52">
            <ResponsiveContainer>
              <ComposedChart data={data} margin={{ left: -20, right: 0, top: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="dia" tick={axis} interval={1} />
                <YAxis yAxisId="n" tick={axis} allowDecimals={false} />
                <YAxis yAxisId="h" orientation="right" tick={axis} hide />
                <Tooltip {...tooltip} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar
                  yAxisId="n"
                  dataKey="Falhas"
                  fill="hsl(var(--status-fault))"
                  radius={[3, 3, 0, 0]}
                />
                <Bar
                  yAxisId="n"
                  dataKey="Reparos"
                  fill="hsl(var(--status-ok))"
                  radius={[3, 3, 0, 0]}
                />
                <Line
                  yAxisId="h"
                  dataKey="MTTR"
                  stroke="hsl(var(--status-maintenance))"
                  dot={false}
                  strokeWidth={2}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
      <section aria-label="Disponibilidade por tipo">
        <h3 className="mb-2 text-sm font-medium">Situação por tipo</h3>
        <div className="h-56">
          <ResponsiveContainer>
            <BarChart data={byType} layout="vertical" margin={{ left: 10, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis type="number" tick={axis} allowDecimals={false} />
              <YAxis type="category" dataKey="tipo" tick={axis} width={70} />
              <Tooltip {...tooltip} />
              <Bar
                dataKey="Operacionais"
                stackId="a"
                fill={`hsl(${EQUIPMENT_STATUS.operacional.color})`}
              />
              <Bar
                dataKey="Indisponíveis"
                stackId="a"
                fill={`hsl(${EQUIPMENT_STATUS.mau_funcionamento.color})`}
                radius={[0, 3, 3, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  );
}
