import { Activity, CalendarClock, RefreshCw, ShieldCheck, Target } from "lucide-react";
import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import { InfoTip } from "@/components/ui/info-tip";
import { Skeleton } from "@/components/ui/primitives";
import { ToneCard, ToneIcon, ToneText, type Tone } from "@/components/ui/tone";
import { useAuth } from "@/lib/auth";
import { fromNow } from "@/lib/format";

import { useAnomalies, useCityForecast, useRefreshPredictions } from "./api";
import { RiskMatrix } from "./RiskMatrix";
import {
  AnomalyList,
  EquipmentRiskList,
  Hotspots,
  ModelQuality,
  Reinforcement,
  Section,
  Trends,
} from "./sections";
import type { CityForecast } from "./types";
import { cap, dayLabel, hourLabel } from "./vocabulary";

const INFO = {
  risk: {
    what: "Quantas falhas, furtos e vandalismos de equipamentos devem acontecer em cada região, hora a hora.",
    data: "Um ano de histórico, o tempo em operação de cada equipamento e o calendário público (feriados, jogos, shows, feiras).",
    help: "Mostra onde e quando concentrar equipes e manutenção antes do problema.",
  },
  hotspots: {
    what: "As faixas de 4 h com mais ocorrências previstas na semana (no máximo 2 por região).",
    data: "A mesma previsão de risco, somada por faixa.",
    help: "Agenda de reforço: o que preparar e para quando.",
  },
  anomalies: {
    what: "Equipamentos prestes a falhar (minutos) e regiões com ocorrências muito acima do normal agora.",
    data: "Telemetria ao vivo comparada com a última hora do próprio equipamento, e a participação histórica de cada região.",
    help: "Dá tempo de acionar a manutenção antes da falha. Precisão e antecedência são medidas ao vivo.",
  },
  staff: {
    what: "Quantos agentes cada região deveria ter em cada faixa de 4 h, comparado com quem está em serviço.",
    data: "Risco previsto por região, efetivo em serviço agora e público esperado em eventos (1 agente a cada 2.000 pessoas).",
    help: "Sugere remanejamentos concretos. Mover efetivo sempre passa por aprovação do gestor.",
  },
  equipment: {
    what: "A chance de cada equipamento operacional falhar nos próximos 3 dias.",
    data: "Taxa de falha do tipo, tendência recente, região, preventiva vencida e o horário/eventos das próximas 72 h.",
    help: "Antecipar a preventiva de poucos equipamentos críticos evita falhas e custa menos que o reparo.",
  },
  trends: {
    what: "Se a disponibilidade de cada tipo de equipamento está caindo e quando cruza a meta de 90%.",
    data: "Situação diária de cada equipamento nos últimos 60 dias (tendência robusta, Theil–Sen).",
    help: "Antecipa renovação de frota e cobrança de SLA antes de virar crise.",
  },
  quality: {
    what: "O quanto dá para confiar nas previsões.",
    data: "Backtest: o modelo foi treinado sem as últimas 8 semanas e previu essas semanas.",
    help: "Mostra o acerto real e o que o modelo aprendeu, sem esconder limitações.",
  },
};

/** Cidade Preditiva: o que pode acontecer, por quê, e o que fazer antes. */
export function PredictionsPage() {
  const city = useCityForecast();
  const anomalies = useAnomalies();
  const { can } = useAuth();
  const refresh = useRefreshPredictions();
  const forecast = city.data?.ready ? city.data.data : undefined;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Cidade Preditiva</h1>
          <p className="text-sm text-muted-foreground">
            O que tende a acontecer, por quê, e onde agir antes.
            {forecast && ` Atualizado ${fromNow(forecast.generated_at)}.`}
          </p>
        </div>
        {can("prometheus:manage") && (
          <Button
            variant="outline"
            size="sm"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            <RefreshCw className={refresh.isPending ? "animate-spin" : undefined} />
            {refresh.isPending ? "Reajustando…" : "Reajustar modelos"}
          </Button>
        )}
      </div>

      {!forecast ? (
        city.isLoading || (city.data && !city.data.ready) ? (
          <div className="space-y-3">
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              Ajustando os modelos com o histórico da cidade. As primeiras previsões aparecem em
              alguns segundos.
            </p>
            <Skeleton className="h-64" />
          </div>
        ) : (
          <p className="text-sm text-destructive">Não foi possível carregar as previsões.</p>
        )
      ) : (
        <>
          <Kpis forecast={forecast} />

          <Section id="risco" title="Onde e quando: risco de ocorrências" info={INFO.risk}>
            <RiskMatrix forecast={forecast} />
          </Section>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section id="agora" title="Fora do padrão agora" info={INFO.anomalies}>
              {anomalies.data?.ready ? (
                <AnomalyList data={anomalies.data.data} />
              ) : (
                <Skeleton className="h-24" />
              )}
            </Section>
            <Section id="janelas" title="Janelas de maior risco da semana" info={INFO.hotspots}>
              <Hotspots forecast={forecast} />
            </Section>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Section id="efetivo" title="Onde posicionar o efetivo" info={INFO.staff}>
              <Reinforcement forecast={forecast} />
            </Section>
            <Section
              id="equipamentos"
              title="Equipamentos que podem falhar em 72 h"
              info={INFO.equipment}
            >
              <EquipmentRiskList items={forecast.equipment_risk} />
            </Section>
          </div>

          <Section
            id="tendencias"
            title="Disponibilidade por tipo de equipamento"
            info={INFO.trends}
          >
            <Trends forecast={forecast} />
          </Section>

          <Section id="qualidade" title="O modelo é confiável?" info={INFO.quality}>
            <ModelQuality forecast={forecast} />
          </Section>
        </>
      )}
    </div>
  );
}

function Kpis({ forecast }: { forecast: CityForecast }) {
  const summary = useMemo(() => {
    const start = new Date(forecast.cells[0]!.at).getTime();
    const total = forecast.cells
      .filter((c) => new Date(c.at).getTime() - start < 24 * 3600_000)
      .reduce((sum, c) => sum + c.expected, 0);
    const nextEvent = forecast.events.find((e) => e.kind !== "feriado") ?? forecast.events[0];
    return { total, peak: forecast.hotspots[0], nextEvent };
  }, [forecast]);
  const cards: {
    tone: Tone;
    icon: typeof Target;
    label: string;
    value: string;
    hint: string;
    info: string;
  }[] = [
    {
      tone: "info",
      icon: Activity,
      label: "Previstas em 24 h",
      value: summary.total.toLocaleString("pt-BR", { maximumFractionDigits: 1 }),
      hint: "ocorrências na cidade",
      info: "Soma das falhas, furtos e vandalismos de equipamentos esperados nas próximas 24 horas, em toda a cidade.",
    },
    {
      tone: "warn",
      icon: Target,
      label: "Janela mais crítica",
      value: summary.peak?.region_name ?? "—",
      hint: summary.peak
        ? `${cap(dayLabel(summary.peak.starts_at))} ${hourLabel(summary.peak.starts_at)}–${hourLabel(summary.peak.ends_at)}`
        : "",
      info: "A faixa de 4 horas da semana com mais ocorrências previstas.",
    },
    {
      tone: "ok",
      icon: ShieldCheck,
      label: "Falhas evitadas",
      value: String(forecast.averted_last_7_days.total),
      hint: `${forecast.averted_last_7_days.by_prometheus} pelo PROMETHEUS · 7 dias`,
      info: "Equipamentos com sinais de falha que receberam intervenção antes de quebrar. Na simulação é contado com certeza; numa cidade real seria uma estimativa.",
    },
    {
      tone: "info",
      icon: CalendarClock,
      label: "Próximo evento",
      value: summary.nextEvent?.name ?? "—",
      hint: summary.nextEvent
        ? `${cap(dayLabel(summary.nextEvent.starts_at))} ${hourLabel(summary.nextEvent.starts_at)}${summary.nextEvent.expected_public ? ` · ~${summary.nextEvent.expected_public.toLocaleString("pt-BR")} pessoas` : ""}`
        : "",
      info: "Evento do calendário público que entra na previsão de risco da região (feriados, jogos, shows, feiras).",
    },
  ];
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <ToneCard key={c.label} as="li" tone={c.tone} className="flex items-start gap-3 p-3">
          <ToneIcon icon={c.icon} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              {c.label}
              <InfoTip title={c.label} content={c.info} />
            </div>
            <ToneText className="block truncate text-lg font-semibold tabular-nums">
              {c.value}
            </ToneText>
            <div className="truncate text-xs text-muted-foreground" title={c.hint}>
              {c.hint}
            </div>
          </div>
        </ToneCard>
      ))}
    </ul>
  );
}
