import { useMemo, useState } from "react";

import { Tooltip } from "@/components/ui/overlays";
import { cn } from "@/lib/utils";

import type { CityForecast, Factor, RiskCell } from "./types";
import { cap, dayLabel, hourLabel } from "./vocabulary";

type View = "24h" | "7d";

const fmt = (value: number, digits = 1) =>
  value.toLocaleString("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

/** Fatores do modelo em linguagem de operador (só os que pesam de verdade). */
export function plainReasons(factors: Factor[] | undefined, limit = 2): string[] {
  if (!factors) return [];
  return factors
    .filter((f) => Math.abs(f.multiplier - 1) >= 0.15)
    .slice(0, limit)
    .map((f) => {
      const pct = Math.round((f.multiplier - 1) * 100);
      const signed = `${pct > 0 ? "+" : ""}${pct}%`;
      const name = f.factor;
      if (/^\d{2}h$/.test(name)) return `horário (${signed})`;
      if (name.startsWith("Região")) return `${name.toLowerCase()} (${signed})`;
      if (name.startsWith("Evento")) return `${name.replace("Evento: ", "evento: ")} (${signed})`;
      if (/^(dia útil|sexta|sábado|domingo)/.test(name)) {
        return `${name.split(" (")[0]} (${signed})`;
      }
      return `época do ano (${signed})`;
    });
}

/** Onde e quando: intensidade única (mais escuro = mais ocorrências esperadas). */
export function RiskMatrix({ forecast }: { forecast: CityForecast }) {
  const [view, setView] = useState<View>("24h");
  const byRegion = useMemo(() => {
    const map = new Map<string, RiskCell[]>();
    forecast.cells.forEach((c) => map.set(c.region, [...(map.get(c.region) ?? []), c]));
    return map;
  }, [forecast.cells]);

  const columns = useMemo(() => {
    const first = byRegion.get(forecast.regions[0]?.code ?? "") ?? [];
    if (view === "24h") return first.slice(0, 24).map((c, i) => ({ start: i, span: 1, at: c.at }));
    const days: { start: number; span: number; at: string }[] = [];
    first.forEach((c, i) => {
      const last = days.at(-1);
      if (last && last.at.slice(0, 10) === c.at.slice(0, 10)) last.span += 1;
      else days.push({ start: i, span: 1, at: c.at });
    });
    return days.slice(0, 7);
  }, [byRegion, forecast.regions, view]);

  const rows = useMemo(
    () =>
      forecast.regions.map((region) => {
        const cells = byRegion.get(region.code) ?? [];
        const values = columns.map((c) => {
          const slice = cells.slice(c.start, c.start + c.span);
          const expected = slice.reduce((sum, x) => sum + x.expected, 0);
          const peak = slice.reduce(
            (best, x) => (x.expected > (best?.expected ?? -1) ? x : best),
            slice[0],
          );
          return { expected, peak, at: c.at };
        });
        const total = values.reduce((sum, v) => sum + v.expected, 0);
        const peakIndex = values.reduce(
          (best, v, i) => (v.expected > (values[best]?.expected ?? 0) ? i : best),
          0,
        );
        return { region, values, total, peakIndex };
      }),
    [byRegion, columns, forecast.regions],
  );
  const max = Math.max(...rows.flatMap((r) => r.values.map((v) => v.expected)), 1e-9);
  const busiest = [...rows].sort((a, b) => b.total - a.total)[0];
  const total = rows.reduce((sum, r) => sum + r.total, 0);
  const peakRow = [...rows].sort(
    (a, b) => (b.values[b.peakIndex]?.expected ?? 0) - (a.values[a.peakIndex]?.expected ?? 0),
  )[0];
  const peak = peakRow?.values[peakRow.peakIndex];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm">
          <strong className="tabular-nums">{fmt(total)}</strong> ocorrências previstas{" "}
          {view === "24h" ? "nas próximas 24 h" : "nos próximos 7 dias"}
          {peakRow && peak && (
            <>
              {" · "}pico: <strong>{peakRow.region.name}</strong>{" "}
              {view === "24h" ? `${dayLabel(peak.at)} às ${hourLabel(peak.at)}` : dayLabel(peak.at)}
            </>
          )}
          {busiest && busiest !== peakRow && (
            <span className="text-muted-foreground"> · mais movimento: {busiest.region.name}</span>
          )}
        </p>
        <div
          role="radiogroup"
          aria-label="Horizonte"
          className="inline-flex rounded-lg bg-muted p-1 text-xs"
        >
          {(["24h", "7d"] as View[]).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={view === option}
              onClick={() => setView(option)}
              className={cn(
                "rounded-md px-3 py-1 font-medium text-muted-foreground transition-colors",
                view === option && "bg-background text-foreground shadow",
              )}
            >
              {option === "24h" ? "24 horas" : "7 dias"}
            </button>
          ))}
        </div>
      </div>

      <div className="fogo-scroll overflow-x-auto">
        <table className="w-full border-separate border-spacing-x-[2px] border-spacing-y-[3px] text-xs">
          <thead>
            <tr>
              <th className="w-28" />
              {columns.map((c, i) => (
                <th
                  key={c.at}
                  className="h-5 min-w-[1.6rem] text-left font-normal text-muted-foreground"
                >
                  {view === "7d" ? (
                    <span className="capitalize">{dayLabel(c.at)}</span>
                  ) : i === 0 ? (
                    <span className="font-medium text-primary">agora</span>
                  ) : i % 3 === 0 ? (
                    hourLabel(c.at)
                  ) : null}
                </th>
              ))}
              <th className="w-16 pl-2 text-right font-normal text-muted-foreground">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ region, values, total: rowTotal, peakIndex }) => (
              <tr key={region.code}>
                <th scope="row" className="whitespace-nowrap pr-2 text-left text-sm font-medium">
                  {region.name}
                </th>
                {values.map((v, i) => {
                  const intensity = v.expected / max;
                  const explain = forecast.explain[`${region.code}|${v.peak?.at ?? v.at}`];
                  const reasons = plainReasons(explain?.factors);
                  const label =
                    view === "24h" ? `${dayLabel(v.at)} ${hourLabel(v.at)}` : dayLabel(v.at);
                  const chance = Math.round((1 - Math.exp(-v.expected)) * 100);
                  return (
                    <td key={v.at} className="p-0">
                      <Tooltip
                        content={
                          <div className="space-y-0.5">
                            <div className="font-medium">
                              {region.name} · {cap(label)}
                            </div>
                            <div>
                              {fmt(v.expected, 2)} ocorrência(s) esperada(s) · {chance}% de chance
                              de ao menos uma
                            </div>
                            {reasons.length > 0 && (
                              <div className="text-muted-foreground">
                                Por quê: {reasons.join(", ")}
                              </div>
                            )}
                          </div>
                        }
                      >
                        <button
                          type="button"
                          aria-label={`${region.name}, ${label}: ${fmt(v.expected, 2)} ocorrências esperadas`}
                          className={cn(
                            "relative block h-8 w-full rounded-[4px] outline-none ring-ring focus-visible:ring-2",
                            i === 0 && view === "24h" && "ring-1 ring-primary/50",
                          )}
                          style={{
                            background: `hsl(var(--sev-alta) / ${(0.06 + 0.86 * intensity).toFixed(3)})`,
                          }}
                        >
                          {i === peakIndex && (
                            <span
                              className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
                              aria-hidden
                            />
                          )}
                        </button>
                      </Tooltip>
                    </td>
                  );
                })}
                <td className="pl-2 text-right text-sm font-semibold tabular-nums">
                  {fmt(rowTotal)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          menos
          <span
            className="h-2 w-24 rounded-full"
            style={{
              background:
                "linear-gradient(90deg, hsl(var(--sev-alta) / 0.06), hsl(var(--sev-alta) / 0.92))",
            }}
            aria-hidden
          />
          mais ocorrências
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-foreground" aria-hidden /> pico da região
        </span>
      </div>
    </div>
  );
}
