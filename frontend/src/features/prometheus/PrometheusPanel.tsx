import { Pause, Play, ShieldCheck, UserCheck, Zap } from "lucide-react";
import { Link } from "react-router-dom";

import { Skeleton } from "@/components/ui/primitives";
import type { Decision, PrometheusMode } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { useDecisions, usePrometheusStats } from "@/features/prediction/api";

import { DecisionCard } from "./DecisionCard";

export const MODE: Record<PrometheusMode, { label: string; hint: string; icon: typeof Play }> = {
  autonomo: {
    label: "Autônomo",
    hint: "Age sozinho no que passar na política; o resto pede aprovação.",
    icon: Play,
  },
  sugestao: { label: "Só sugestão", hint: "Toda ação pede aprovação humana.", icon: UserCheck },
  pausado: { label: "Pausado", hint: "Não abre novas decisões.", icon: Pause },
};

/** Aba PROMETHEUS da Central: pedidos de aprovação e o que o agente fez. */
export function PrometheusPanel() {
  const decisions = useDecisions();
  const stats = usePrometheusStats();
  const items = decisions.data ?? [];
  const pending = items.filter((d) => d.status === "pendente");
  const recent = items.filter((d) => d.status !== "pendente").slice(0, 12);
  const s = stats.data;
  const mode = s ? MODE[s.mode] : undefined;

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {mode && (
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium",
              s?.mode === "autonomo" && "border-[hsl(var(--status-ok)/0.5)] text-status-ok",
            )}
            title={mode.hint}
          >
            <mode.icon className="h-3.5 w-3.5" aria-hidden /> {mode.label}
          </span>
        )}
        {s && (
          <dl className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
            <Stat icon={Zap} label="sozinho" value={s.decisions.auto ?? 0} />
            <Stat icon={UserCheck} label="aprovadas" value={s.decisions.approved ?? 0} />
            <Stat icon={ShieldCheck} label="falhas evitadas" value={s.averted.total ?? 0} />
          </dl>
        )}
        <span className="text-muted-foreground">nas últimas 24 h</span>
      </div>

      <section aria-labelledby="prometheus-pendentes" className="space-y-2">
        <h3 id="prometheus-pendentes" className="text-xs font-medium text-muted-foreground">
          Aguardando sua decisão ({pending.length})
        </h3>
        {decisions.isLoading ? (
          <Skeleton className="h-24" />
        ) : pending.length ? (
          pending.map((d) => (
            <DecisionCard key={d.id} decision={d} defaultOpen={pending.length === 1} />
          ))
        ) : (
          <p className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
            Nenhum pedido de aprovação agora.
          </p>
        )}
      </section>

      <section aria-labelledby="prometheus-atividade" className="space-y-2">
        <h3 id="prometheus-atividade" className="text-xs font-medium text-muted-foreground">
          Atividade recente
        </h3>
        {recent.length ? (
          recent.map((d: Decision) => <DecisionCard key={d.id} decision={d} />)
        ) : (
          <p className="text-xs text-muted-foreground">
            O PROMETHEUS ainda não agiu. Ele avalia a cidade a cada minuto.
          </p>
        )}
      </section>
      <p className="text-[11px] text-muted-foreground">
        Previsões completas em{" "}
        <Link to="/previsoes" className="text-primary underline-offset-2 hover:underline">
          Cidade Preditiva
        </Link>
        . Política de autonomia em Administração.
      </p>
    </div>
  );
}

function Stat({ icon: Icon, label, value }: { icon: typeof Zap; label: string; value: number }) {
  return (
    <div className="flex items-center gap-1">
      <Icon className="h-3.5 w-3.5" aria-hidden />
      <dd className="font-semibold tabular-nums text-foreground">{value}</dd>
      <dt>{label}</dt>
    </div>
  );
}
