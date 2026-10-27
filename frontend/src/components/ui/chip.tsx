import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Opção de filtro em formato de chip (botão alternável, com contagem opcional). */
export function Chip({
  pressed,
  onToggle,
  children,
  count,
  title,
}: {
  pressed: boolean;
  onToggle: () => void;
  children: ReactNode;
  count?: number;
  title?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      title={title}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs transition-colors",
        pressed
          ? "border-primary/60 bg-primary/15 text-foreground"
          : "bg-background/40 text-muted-foreground hover:border-foreground/25 hover:text-foreground",
      )}
    >
      {children}
      {count !== undefined && (
        <span className="text-[10px] tabular-nums text-muted-foreground">{count}</span>
      )}
    </button>
  );
}
