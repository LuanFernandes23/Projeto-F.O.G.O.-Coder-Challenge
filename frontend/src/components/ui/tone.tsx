// Cartões com "tom" semântico: verde = bom, âmbar = atenção, vermelho = ruim, azul = informativo.
// A cor nunca vem sozinha: o conteúdo do cartão sempre traz o rótulo/valor em texto.
import { forwardRef } from "react";
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "bad" | "info" | "neutral";

export const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--status-ok)",
  warn: "var(--status-maintenance)",
  bad: "var(--status-fault)",
  info: "var(--tone-info)",
  neutral: "var(--muted-foreground)",
};

/** Estilo que define `--tone`; `color` (tripla HSL, ex. "var(--sev-alta)") sobrepõe o tom. */
export function toneStyle(tone: Tone, color?: string): CSSProperties {
  return { "--tone": color ?? TONE_COLOR[tone] } as CSSProperties;
}

/** Disponibilidade/percentual: ≥ 95 bom, ≥ 85 atenção, abaixo disso ruim. */
export function percentTone(pct: number): Tone {
  return pct >= 95 ? "ok" : pct >= 85 ? "warn" : "bad";
}

type ToneCardProps = HTMLAttributes<HTMLElement> & {
  tone: Tone;
  color?: string;
  as?: "div" | "li" | "article";
  /** Brilho radial no canto; desligue em listas longas para não poluir. */
  glow?: boolean;
};

export const ToneCard = forwardRef<HTMLElement, ToneCardProps>(
  ({ tone, color, as: Tag = "div", glow = true, className, style, ...props }, ref) => (
    <Tag
      ref={ref as never}
      className={cn("tone-card", glow && "tone-card--glow", className)}
      style={{ ...toneStyle(tone, color), ...style }}
      {...props}
    />
  ),
);
ToneCard.displayName = "ToneCard";

/** Ladrilho do ícone tingido com o tom do cartão pai (ou o próprio). */
export function ToneIcon({
  icon: Icon,
  className,
  solid = false,
}: {
  icon: LucideIcon;
  className?: string;
  solid?: boolean;
}) {
  return (
    <span
      className={cn(
        "grid h-9 w-9 shrink-0 place-items-center rounded-lg",
        solid
          ? "bg-[linear-gradient(135deg,hsl(var(--tone)),hsl(var(--tone)/0.7))] text-white shadow-[0_4px_12px_-4px_hsl(var(--tone)/0.6)]"
          : "bg-[hsl(var(--tone)/0.13)] text-[hsl(var(--tone))]",
        className,
      )}
      aria-hidden
    >
      <Icon className="h-[18px] w-[18px]" />
    </span>
  );
}

/** Barra de progresso fina no tom do cartão. */
export function ToneBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className="h-1 overflow-hidden rounded-full bg-[hsl(var(--tone)/0.15)]"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <div
        className="h-full rounded-full bg-[hsl(var(--tone))] transition-[width] duration-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

/** Texto no tom do cartão (valor principal). */
export function ToneText({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("text-[hsl(var(--tone))]", className)}>{children}</span>;
}
