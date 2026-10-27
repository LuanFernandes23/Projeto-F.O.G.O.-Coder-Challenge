// Linguagem visual das previsões (cor + rótulo, nunca só cor).
import type { RiskLevel } from "./types";

export const RISK: Record<RiskLevel, { label: string; color: string; fill: number }> = {
  baixo: { label: "Baixo", color: "var(--status-ok)", fill: 0.1 },
  moderado: { label: "Moderado", color: "var(--sev-media)", fill: 0.22 },
  alto: { label: "Alto", color: "var(--sev-alta)", fill: 0.34 },
  muito_alto: { label: "Muito alto", color: "var(--sev-critica)", fill: 0.46 },
};

export const GROUP_LABEL: Record<string, string> = {
  transito: "Trânsito",
  espaco_publico: "Espaço público",
  frota_e_outros: "Frota e outros",
};

export const WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

export const pct = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined
    ? "—"
    : `${(value * 100).toLocaleString("pt-BR", { maximumFractionDigits: digits })}%`;

export const signedPct = (value: number) =>
  `${value >= 0 ? "+" : ""}${(value * 100).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}%`;

export const hourLabel = (iso: string) => `${iso.slice(11, 13)}h`;

export function dayLabel(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T12:00:00`);
  const today = new Date();
  const diff = Math.round(
    (date.getTime() - new Date(today.toDateString()).getTime() - 12 * 3600_000) / 86_400_000,
  );
  if (diff === 0) return "hoje";
  if (diff === 1) return "amanhã";
  return `${WEEKDAYS[(date.getDay() + 6) % 7]} ${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
}

export const cap = (text: string) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : text);
