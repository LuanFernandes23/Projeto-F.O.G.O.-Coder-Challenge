import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Gauge,
  Radio,
  ShieldCheck,
  Wrench,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/primitives";
import { percentTone, ToneBar, ToneIcon, toneStyle, type Tone } from "@/components/ui/tone";
import type { Overview } from "@/lib/api/types";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export type KpiFilter =
  "todos" | "operacionais" | "indisponiveis" | "offline" | "manutencao" | "alertas";

interface Kpi {
  id: KpiFilter | "agentes" | "disponibilidade";
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone: Tone;
  /** Percentual exibido como barra no rodapé do cartão. */
  progress?: number;
}

function kpis(o: Overview): Kpi[] {
  const critical = o.alerts_by_severity.critica ?? 0;
  const installed = o.online + o.offline;
  const onlinePct = installed ? (o.online / installed) * 100 : 100;
  return [
    {
      id: "todos",
      label: "Equipamentos",
      value: formatNumber(o.total_equipment),
      hint: "no inventário",
      icon: Activity,
      tone: "info",
    },
    {
      id: "operacionais",
      label: "Operacionais",
      value: formatNumber(o.operational),
      hint: "funcionando agora",
      icon: CheckCircle2,
      tone: "ok",
    },
    {
      id: "indisponiveis",
      label: "Indisponíveis",
      value: formatNumber(o.unavailable),
      hint: "defeito, manutenção ou furto",
      icon: XCircle,
      tone: o.unavailable ? "bad" : "ok",
    },
    {
      id: "disponibilidade",
      label: "Disponibilidade",
      value: formatPercent(o.availability_pct),
      icon: Gauge,
      tone: percentTone(o.availability_pct),
      progress: o.availability_pct,
    },
    {
      id: "offline",
      label: "Online",
      value: formatNumber(o.online),
      hint: `${formatNumber(o.offline)} sem comunicação`,
      icon: Radio,
      tone: o.offline ? "warn" : "ok",
      progress: onlinePct,
    },
    {
      id: "manutencao",
      label: "Reparo imediato",
      value: formatNumber(o.maintenance_immediate),
      hint: `${formatNumber(o.maintenance_overdue)} vencidas · ${formatNumber(o.maintenance_due_soon)} em 7 dias`,
      icon: Wrench,
      tone: o.maintenance_immediate ? "warn" : "ok",
    },
    {
      id: "agentes",
      label: "Agentes em serviço",
      value: formatNumber(o.agents_on_duty),
      hint: `${formatNumber(o.agents_dispatched)} em despacho`,
      icon: ShieldCheck,
      tone: "info",
    },
    {
      id: "alertas",
      label: "Alertas abertos",
      value: formatNumber(o.alerts_open),
      hint: `${critical} crítico(s) · ${o.alerts_sla_breached} fora do SLA`,
      icon: AlertOctagon,
      tone: critical || o.alerts_sla_breached ? "bad" : o.alerts_open ? "warn" : "ok",
    },
  ];
}

const GRID = "grid grid-cols-2 gap-2.5 px-3 py-2.5 sm:grid-cols-4 xl:grid-cols-8";

export function KpiBar({
  overview,
  active,
  onSelect,
}: {
  overview: Overview | undefined;
  active: KpiFilter | null;
  onSelect: (filter: KpiFilter) => void;
}) {
  if (!overview) {
    return (
      <div className={GRID}>
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-[74px]" />
        ))}
      </div>
    );
  }
  return (
    <section className={GRID} aria-label="Indicadores da cidade">
      {kpis(overview).map((kpi) => {
        const clickable = kpi.id !== "agentes" && kpi.id !== "disponibilidade";
        const content = (
          <>
            <div className="flex items-start gap-2.5">
              <ToneIcon icon={kpi.icon} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs text-muted-foreground">{kpi.label}</div>
                <div className="text-xl font-semibold leading-tight tabular-nums text-[hsl(var(--tone))]">
                  {kpi.value}
                </div>
              </div>
            </div>
            {kpi.progress !== undefined ? (
              <div className="mt-2">
                <ToneBar value={kpi.progress} />
                {kpi.hint && <span className="sr-only">{kpi.hint}</span>}
              </div>
            ) : (
              kpi.hint && (
                <div className="mt-1 truncate text-[11px] text-muted-foreground">{kpi.hint}</div>
              )
            )}
          </>
        );
        const className = cn(
          "tone-card tone-card--glow flex min-w-0 flex-col justify-between px-3 py-2.5 text-left",
          clickable && "cursor-pointer active:scale-[0.98]",
        );
        return clickable ? (
          <button
            key={kpi.id}
            type="button"
            className={className}
            style={toneStyle(kpi.tone)}
            aria-pressed={active === kpi.id}
            title={`Filtrar o mapa: ${kpi.label.toLowerCase()}`}
            onClick={() => onSelect(kpi.id as KpiFilter)}
          >
            {content}
          </button>
        ) : (
          <div key={kpi.id} className={className} style={toneStyle(kpi.tone)} title={kpi.hint}>
            {content}
          </div>
        );
      })}
    </section>
  );
}
