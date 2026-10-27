import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  ChevronDown,
  Minus,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { InfoTip, type InfoContent } from "@/components/ui/info-tip";
import { Badge } from "@/components/ui/primitives";
import { ToneBar, ToneCard, type Tone } from "@/components/ui/tone";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { typeIcon } from "@/lib/vocabulary";

import { useOpenPreventiveOrder } from "./api";
import { plainReasons } from "./RiskMatrix";
import type { AnomalySnapshot, CityForecast, EquipmentRisk } from "./types";
import { cap, dayLabel, hourLabel, pct, signedPct } from "./vocabulary";

export function Section({
  id,
  title,
  subtitle,
  info,
  children,
  action,
}: {
  id: string;
  title: string;
  subtitle?: string;
  info?: InfoContent;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className="space-y-3 rounded-xl border bg-card p-4 shadow-[var(--shadow-card)]"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={id} className="flex items-center gap-1.5 font-semibold">
            {title}
            {info && <InfoTip title={title} content={info} />}
          </h2>
          {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Metric({
  label,
  value,
  info,
  tone,
  note,
}: {
  label: string;
  value: string;
  info: string;
  tone?: Tone;
  note?: string;
}) {
  return (
    <div className="rounded-lg border p-2.5">
      <dt className="flex items-center gap-1 text-xs text-muted-foreground">
        {label}
        <InfoTip title={label} content={info} />
      </dt>
      <dd
        className={cn(
          "text-lg font-semibold tabular-nums",
          tone === "ok" && "text-status-ok",
          tone === "warn" && "text-[hsl(var(--sev-media))]",
        )}
      >
        {value}
      </dd>
      {note && <dd className="text-[11px] text-muted-foreground">{note}</dd>}
    </div>
  );
}

// ---- onde e quando ---------------------------------------------------------------------

export function Hotspots({ forecast }: { forecast: CityForecast }) {
  return (
    <ol className="divide-y rounded-lg border">
      {forecast.hotspots.map((h, i) => {
        const reasons = plainReasons(h.factors, 2);
        return (
          <li key={`${h.region}${h.starts_at}`} className="flex items-start gap-3 p-3 text-sm">
            <span className="mt-0.5 w-4 text-right font-semibold tabular-nums text-muted-foreground">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {h.region_name} · {cap(dayLabel(h.starts_at))} {hourLabel(h.starts_at)}–
                {hourLabel(h.ends_at)}
              </div>
              <div className="text-xs text-muted-foreground">
                {reasons.length
                  ? `Por quê: ${reasons.join(", ")}`
                  : "Volume alto de equipamentos na região"}
                {h.events.length > 0 && (
                  <span className="ml-1 inline-flex items-center gap-1">
                    · <CalendarDays className="h-3 w-3" aria-hidden /> {h.events.join(", ")}
                  </span>
                )}
              </div>
            </div>
            <span className="shrink-0 rounded-full bg-[hsl(var(--sev-alta)/0.15)] px-2 py-0.5 text-xs font-semibold tabular-nums text-[hsl(var(--sev-alta))]">
              {h.ratio.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}× a média
            </span>
          </li>
        );
      })}
    </ol>
  );
}

// ---- efetivo -------------------------------------------------------------------------------

export function Reinforcement({ forecast }: { forecast: CityForecast }) {
  const names = Object.fromEntries(forecast.regions.map((r) => [r.code, r.name]));
  const [index, setIndex] = useState(0);
  const block = forecast.reinforcement[index];
  if (!block) return null;
  const max = Math.max(...block.regions.flatMap((r) => [r.staffed, r.recommended]), 1);
  return (
    <div className="space-y-3">
      <div
        role="radiogroup"
        aria-label="Faixa de horário"
        className="inline-flex rounded-lg bg-muted p-1 text-xs"
      >
        {forecast.reinforcement.map((b, i) => (
          <button
            key={b.starts_at}
            type="button"
            role="radio"
            aria-checked={i === index}
            onClick={() => setIndex(i)}
            className={cn(
              "rounded-md px-3 py-1 font-medium text-muted-foreground",
              i === index && "bg-background text-foreground shadow",
            )}
          >
            {hourLabel(b.starts_at)}–{hourLabel(b.ends_at)}
          </button>
        ))}
      </div>
      <ul className="space-y-2">
        {block.regions.map((r) => (
          <li
            key={r.region}
            className="grid grid-cols-[7rem_1fr_6rem] items-center gap-3 text-sm"
            title={r.reason}
          >
            <span className="truncate">{r.region_name}</span>
            <div className="relative h-5 rounded bg-muted" aria-hidden>
              <div
                className="absolute inset-y-0 left-0 rounded bg-primary/35"
                style={{ width: `${(r.staffed / max) * 100}%` }}
              />
              <div
                className="absolute inset-y-0 w-0.5 bg-foreground"
                style={{ left: `calc(${(r.recommended / max) * 100}% - 1px)` }}
              />
            </div>
            <span className="text-right tabular-nums">
              {r.staffed} → <strong>{r.recommended}</strong>
              {r.gap !== 0 && (
                <span
                  className={cn(
                    "ml-1 text-xs",
                    r.gap > 0 ? "text-[hsl(var(--sev-alta))]" : "text-muted-foreground",
                  )}
                >
                  ({r.gap > 0 ? `+${r.gap}` : r.gap})
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-4 rounded-sm bg-primary/35" aria-hidden /> em serviço agora
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-0.5 bg-foreground" aria-hidden /> recomendado
        </span>
      </p>
      {block.moves.length > 0 ? (
        <ul className="space-y-1 rounded-lg border border-dashed p-2.5 text-sm">
          {block.moves.map((m) => (
            <li key={`${m.from}${m.to}`} className="flex items-center gap-1.5">
              Sugestão: mover <strong>{m.agents}</strong> agente(s) de {names[m.from]}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden /> {names[m.to]}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Distribuição atual adequada nesta faixa.</p>
      )}
    </div>
  );
}

// ---- equipamentos em risco --------------------------------------------------------------

function riskTone(p: number): Tone {
  return p >= 0.3 ? "bad" : p >= 0.15 ? "warn" : "info";
}

export function EquipmentRiskList({ items }: { items: EquipmentRisk[] }) {
  const { can } = useAuth();
  const openOrder = useOpenPreventiveOrder();
  return (
    <ul className="divide-y rounded-lg border">
      {items.slice(0, 10).map((d) => {
        const Icon = typeIcon(d.type_code);
        const reasons = d.factors
          .filter((f) => f.multiplier >= 1.15)
          .slice(0, 2)
          .map((f) => f.factor.toLowerCase());
        return (
          <li
            key={d.equipment_id}
            className="grid items-center gap-3 p-3 sm:grid-cols-[1fr_8rem_auto]"
          >
            <div className="flex min-w-0 items-start gap-2.5">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">
                  {d.type_name} {d.serial_number}
                  {d.overdue && (
                    <Badge className="ml-2 bg-[hsl(var(--sev-media)/0.15)] text-[hsl(var(--sev-media))]">
                      Preventiva vencida
                    </Badge>
                  )}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {d.neighborhood}
                  {reasons.length > 0 && ` · ${reasons.join(", ")}`}
                </div>
              </div>
            </div>
            <ToneCard
              tone={riskTone(d.probability_72h)}
              glow={false}
              className="space-y-1 border-0 p-0 shadow-none"
            >
              <div className="text-right text-sm font-semibold tabular-nums text-[hsl(var(--tone))]">
                {pct(d.probability_72h)}
              </div>
              <ToneBar
                value={d.probability_72h * 100}
                label={`Chance de falha em 72 h: ${pct(d.probability_72h)}`}
              />
            </ToneCard>
            {can("maintenance:order_operate") && (
              <Button
                size="xs"
                variant="outline"
                disabled={openOrder.isPending}
                onClick={() =>
                  openOrder.mutate({
                    equipmentId: d.equipment_id,
                    description: `Antecipar preventiva: ${pct(d.probability_72h)} de chance de falha em 72 h.`,
                  })
                }
              >
                <Wrench /> Antecipar preventiva
              </Button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// ---- anomalias ----------------------------------------------------------------------------

/** Abaixo disto a API não calcula a porcentagem (mesmo valor de MIN_CASES no backend). */
const MIN_CASES = 10;

export function AnomalyList({ data }: { data: AnomalySnapshot }) {
  const q = data.quality;
  const learning = data.learning;
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Metric
          label="Precisão"
          value={q.precision == null ? "—" : pct(q.precision)}
          note={q.precision == null ? `poucos casos (${q.decided} de ${MIN_CASES})` : undefined}
          info="Das detecções já concluídas nas últimas 24 h, quantas eram falha de verdade (falharam ou foram evitadas)."
        />
        <Metric
          label="Cobertura"
          value={q.recall == null ? "—" : pct(q.recall)}
          note={q.recall == null ? `poucos casos (${q.live_failures} de ${MIN_CASES})` : undefined}
          info="Das falhas que aconteceram ao vivo, quantas tiveram aviso antes."
        />
        <Metric
          label="Antecedência"
          value={q.mean_lead_minutes ? `${q.mean_lead_minutes.toLocaleString("pt-BR")} min` : "—"}
          info="Tempo médio entre o aviso e a falha: é a janela que a equipe tem para agir."
        />
        <Metric
          label="Falhas evitadas"
          value={String(q.detections_averted)}
          tone="ok"
          info="Equipamentos que receberam intervenção antes de falhar (24 h)."
        />
      </dl>

      {data.devices.length === 0 && data.regional.length === 0 ? (
        <p className="rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
          Nenhum comportamento fora do padrão agora.
        </p>
      ) : (
        <ul className="space-y-2">
          {data.regional.map((r) => (
            <ToneCard key={r.region} as="li" tone="bad" className="p-3 text-sm">
              <strong>{r.region_name ?? r.region}</strong>: {r.observed} ocorrências nas últimas 3 h
              (o normal seria {r.expected.toLocaleString("pt-BR")})
            </ToneCard>
          ))}
          {data.devices.map((d) => {
            const Icon = typeIcon(d.type_code);
            return (
              <ToneCard
                key={d.equipment_id}
                as="li"
                tone="warn"
                className="flex items-start gap-2.5 p-3"
              >
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--tone))]" aria-hidden />
                <div className="min-w-0 flex-1 text-sm">
                  <div className="font-medium">
                    {d.serial_number}{" "}
                    <span className="font-normal text-muted-foreground">· {d.neighborhood}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {d.signals.map((s) => `${s.label.toLowerCase()} ${s.value}`).join(" · ")}
                  </div>
                </div>
                {typeof d.p_real === "number" && (
                  <span
                    className="shrink-0 text-right text-xs"
                    title="Probabilidade de ser falha real, pelo modelo que aprende com os desfechos"
                  >
                    <span className="block text-sm font-semibold tabular-nums">
                      {pct(d.p_real)}
                    </span>
                    chance de falha real
                  </span>
                )}
              </ToneCard>
            );
          })}
        </ul>
      )}

      {learning && (
        <div className="rounded-lg border bg-muted/30 p-3 text-sm">
          <div className="flex items-center gap-1.5 font-medium">
            Aprendizado contínuo
            <InfoTip
              title="Aprendizado contínuo"
              content={{
                what: "Um classificador (regressão logística) que estima se cada alarme é falha real ou alarme falso.",
                data: "O desfecho de cada detecção: falhou, foi evitada ou era alarme falso. Retreina sozinho a cada novo desfecho.",
                help: "Quanto mais o sistema opera, menos alarmes falsos. A probabilidade dele é a confiança que o PROMETHEUS usa para decidir se age sozinho.",
              }}
            />
          </div>
          {learning.active ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Treinado com <strong className="text-foreground">{learning.labels}</strong> desfechos.
              {learning.metrics.precision_model != null &&
                learning.metrics.precision_rule != null && (
                  <>
                    {" "}
                    Nos casos mais recentes, acertou {pct(learning.metrics.precision_model)} dos que
                    apontou como falha real, contra {pct(learning.metrics.precision_rule)} da regra
                    “todo alarme é falha”.
                  </>
                )}
              {learning.explain.length > 0 && (
                <> O sinal que mais pesa: {learning.explain[0]!.feature}.</>
              )}
            </p>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">
              Aguardando desfechos suficientes ({learning.labels} de {learning.min_labels}) para
              treinar.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ---- tendências ---------------------------------------------------------------------------

const TYPE_NAMES: Record<string, string> = {
  patinete: "Patinetes",
  camera: "Câmeras",
  semaforo: "Semáforos",
  radar: "Radares",
  totem_estacionamento: "Totens de estacionamento",
  viatura: "Viaturas",
  moto_agente: "Motos de agentes",
  cancela: "Cancelas",
  balanca: "Balanças",
  veiculo_transporte: "Veículos de transporte",
  veiculo_fiscalizacao_autonomo: "Fiscalização autônoma",
  outro: "Outros",
};

function Sparkline({ values, tone }: { values: number[]; tone: Tone }) {
  if (values.length < 2) return null;
  const min = Math.min(...values, 90);
  const max = Math.max(...values, 100);
  const points = values
    .map(
      (v, i) =>
        `${(i / (values.length - 1)) * 100},${30 - ((v - min) / (max - min || 1)) * 28 - 1}`,
    )
    .join(" ");
  const target = 30 - ((90 - min) / (max - min || 1)) * 28 - 1;
  const color =
    tone === "bad"
      ? "var(--status-fault)"
      : tone === "ok"
        ? "var(--status-ok)"
        : "var(--tone-info)";
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-full" aria-hidden>
      <line
        x1="0"
        x2="100"
        y1={target}
        y2={target}
        stroke="hsl(var(--muted-foreground))"
        strokeDasharray="2 2"
        strokeWidth="0.6"
      />
      <polyline
        points={points}
        fill="none"
        stroke={`hsl(${color})`}
        strokeWidth="1.6"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export function Trends({ forecast }: { forecast: CityForecast }) {
  const items = forecast.trends
    .filter((t) => t.series.length >= 14)
    .map((t) => {
      const current = t.series.at(-1)?.value ?? 0;
      const below = Boolean(t.crosses_on && t.crosses_on <= (t.series.at(-1)?.date ?? ""));
      const tone: Tone =
        below || t.status === "queda" ? "bad" : t.status === "alta" ? "ok" : "info";
      const weeks =
        t.crosses_on && !below
          ? Math.max(
              1,
              Math.round(
                (new Date(`${t.crosses_on}T12:00:00`).getTime() - Date.now()) / (7 * 86_400_000),
              ),
            )
          : null;
      const message = below
        ? "abaixo da meta de 90%"
        : weeks
          ? `abaixo de 90% em ~${weeks} semana(s)`
          : t.status === "queda"
            ? "em queda, ainda acima da meta"
            : t.status === "alta"
              ? "melhorando"
              : "estável";
      return {
        t,
        current,
        tone,
        message,
        rank: below ? 0 : weeks ? 1 : t.status === "queda" ? 2 : 3,
      };
    })
    .sort((a, b) => a.rank - b.rank || a.t.slope_per_week - b.t.slope_per_week);

  return (
    <ul className="divide-y rounded-lg border">
      {items.map(({ t, current, tone, message }) => {
        const Arrow =
          t.slope_per_week <= -0.3
            ? ArrowDownRight
            : t.slope_per_week >= 0.3
              ? ArrowUpRight
              : Minus;
        return (
          <li
            key={t.type_code}
            className="grid grid-cols-[1fr_6rem] items-center gap-3 p-3 sm:grid-cols-[12rem_1fr_7rem_12rem]"
          >
            <span className="text-sm font-medium">{TYPE_NAMES[t.type_code] ?? t.type_code}</span>
            <div className="hidden sm:block">
              <Sparkline values={t.series.map((p) => p.value)} tone={tone} />
            </div>
            <span className="text-right text-sm tabular-nums">
              <strong>{current.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}%</strong>
              <span className="ml-1 inline-flex items-center text-xs text-muted-foreground">
                <Arrow className="h-3 w-3" aria-hidden />
                {Math.abs(t.slope_per_week).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}
                /sem
              </span>
            </span>
            <span
              className={cn(
                "col-span-2 text-xs sm:col-span-1 sm:text-right",
                tone === "bad"
                  ? "font-medium text-[hsl(var(--status-fault))]"
                  : "text-muted-foreground",
              )}
            >
              {message}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ---- qualidade do modelo ------------------------------------------------------------------

export function ModelQuality({ forecast }: { forecast: CityForecast }) {
  const [open, setOpen] = useState(false);
  const b = forecast.backtest;
  const effects = [
    ...forecast.model.factors.region.map((r) => ({
      label: `Região ${r.name}`,
      value: r.multiplier,
    })),
    ...Object.entries(forecast.model.factors.event).flatMap(([group, kinds]) =>
      Object.entries(kinds).map(([kind, value]) => ({
        label: `${cap(kind === "feriado" ? "feriados" : kind === "esporte" ? "jogos" : kind === "cultura" ? "shows" : "feiras")} (${group === "transito" ? "trânsito" : group === "espaco_publico" ? "espaço público" : "frota"})`,
        value,
      })),
    ),
    {
      label: "Preventiva vencida",
      value: forecast.model.equipment.overdue_factor,
    },
  ]
    .filter((e) => Math.abs(e.value - 1) >= 0.2)
    .sort((a, b2) => Math.abs(b2.value - 1) - Math.abs(a.value - 1))
    .slice(0, 6);
  const peakHour = forecast.model.factors.hour.reduce(
    (best, v, h, all) => (v > (all[best] ?? 0) ? h : best),
    0,
  );
  const calibration = b.calibration.predicted
    .map((p, i) => ({ p, o: b.calibration.observed[i] ?? 0, n: b.calibration.counts[i] ?? 0 }))
    .filter((c) => c.n >= 20);
  const midBin = calibration[Math.floor(calibration.length / 2)];

  return (
    <div className="space-y-3">
      <dl className="grid gap-2 sm:grid-cols-3">
        <Metric
          label="Acerto contra a média"
          value={signedPct(b.skill_vs_mean)}
          tone={b.skill_vs_mean > 0.05 ? "ok" : "warn"}
          info="Quanto o erro do modelo é menor que o de uma previsão ingênua (a média histórica), nas 8 semanas que ele não viu."
        />
        <Metric
          label="Concentração do risco"
          value={pct(b.top20_capture)}
          info="Das ocorrências reais do teste, quantas caíram nos 20% de horários e regiões que o modelo apontou como mais arriscados. Ao acaso seriam 20%."
        />
        <Metric
          label="Contra o perfil por hora"
          value={Math.abs(b.skill_vs_hour) < 0.02 ? "empate" : signedPct(b.skill_vs_hour)}
          info="Comparação com uma previsão que já conhece o horário do dia. Empate = o horário explica a maior parte do volume; os demais fatores refinam onde e quando."
        />
      </dl>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronDown
          className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
          aria-hidden
        />
        O que o modelo aprendeu e como foi testado
      </button>
      {open && (
        <div className="grid gap-4 rounded-lg border p-3 text-sm md:grid-cols-2">
          <div className="space-y-2">
            <p className="font-medium">Efeitos que o modelo encontrou no histórico</p>
            <ul className="space-y-1.5">
              <li className="flex justify-between gap-2">
                <span>Horário de pico</span>
                <span className="tabular-nums text-muted-foreground">
                  {peakHour}h ({signedPct((forecast.model.factors.hour[peakHour] ?? 1) - 1)})
                </span>
              </li>
              {effects.map((e) => (
                <li key={e.label} className="flex justify-between gap-2">
                  <span>{e.label}</span>
                  <span
                    className={cn(
                      "tabular-nums",
                      e.value > 1 ? "text-[hsl(var(--sev-alta))]" : "text-status-ok",
                    )}
                  >
                    {signedPct(e.value - 1)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-2 text-muted-foreground">
            <p className="font-medium text-foreground">Como foi testado</p>
            <p>
              Treinado com {forecast.model.observed_events.toLocaleString("pt-BR")} ocorrências do
              último ano, sem as últimas 8 semanas; depois previu essas {b.test_days} dias (
              {b.test_events} ocorrências reais).
            </p>
            {midBin && (
              <p>
                Calibração: quando o modelo diz {pct(midBin.p)} de chance, aconteceu em{" "}
                {pct(midBin.o)} dos casos.
              </p>
            )}
            {forecast.model.excluded_days.length > 0 && (
              <p>
                {forecast.model.excluded_days.length} dia(s) com volume anômalo ficaram fora do
                treino.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
