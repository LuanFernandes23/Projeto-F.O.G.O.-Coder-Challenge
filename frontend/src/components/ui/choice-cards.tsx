// Grupo de escolha única em cartões (ícone + rótulo + descrição), acessível como radiogroup.
// Setas movem a seleção, como num grupo de rádios nativo.
import type { KeyboardEvent } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Choice<T extends string> {
  value: T;
  label: string;
  description?: string;
  icon: LucideIcon;
  disabled?: boolean;
}

export function ChoiceCards<T extends string>({
  value,
  onChange,
  choices,
  label,
  invalid,
  className,
}: {
  value: T | "";
  onChange: (value: T) => void;
  choices: Choice<T>[];
  label: string;
  invalid?: boolean;
  className?: string;
}) {
  const enabled = choices.filter((c) => !c.disabled);
  const focusable = value && enabled.some((c) => c.value === value) ? value : enabled[0]?.value;

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, current: T) => {
    const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = enabled.findIndex((c) => c.value === current);
    const next = enabled[(index + step + enabled.length) % enabled.length];
    if (!next) return;
    onChange(next.value);
    const group = event.currentTarget.parentElement;
    group?.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-invalid={invalid}
      className={cn("grid gap-2 sm:grid-cols-2", className)}
    >
      {choices.map(({ value: v, label: l, description, icon: Icon, disabled }) => {
        const checked = v === value;
        return (
          <button
            key={v}
            type="button"
            role="radio"
            data-value={v}
            aria-checked={checked}
            disabled={disabled}
            tabIndex={v === focusable ? 0 : -1}
            onClick={() => onChange(v)}
            onKeyDown={(e) => onKeyDown(e, v)}
            className={cn(
              "flex items-start gap-3 rounded-lg border bg-background p-3 text-left transition-colors hover:border-primary/50 disabled:cursor-not-allowed disabled:opacity-50",
              checked && "border-primary bg-primary/5 ring-1 ring-primary/40",
              invalid && !value && "border-destructive",
            )}
          >
            <span
              className={cn(
                "grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground",
                checked && "bg-primary/15 text-primary",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium">{l}</span>
              {description && (
                <span className="block text-xs text-muted-foreground">{description}</span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
