// Ícone (?) com a explicação de uma previsão ou métrica. Abre no hover, no foco (teclado) e no
// toque; o conteúdo segue o formato exigido pelo enunciado: o que prevê, dados e como ajuda.
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { CircleHelp } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface InfoContent {
  what: string;
  data?: string;
  help?: string;
}

export function InfoTip({
  title,
  content,
  className,
}: {
  title: string;
  content: InfoContent | ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const structured = typeof content === "object" && content !== null && "what" in content;
  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger
        type="button"
        aria-label={`O que é: ${title}`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className={cn(
          "inline-grid h-5 w-5 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground",
          className,
        )}
      >
        <CircleHelp className="h-3.5 w-3.5" aria-hidden />
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="start"
          sideOffset={6}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-[1300] w-72 space-y-1.5 rounded-lg border bg-popover p-3 text-xs text-popover-foreground shadow-lg"
        >
          <p className="font-medium">{title}</p>
          {structured ? (
            <dl className="space-y-1.5">
              <div>
                <dt className="text-muted-foreground">O que é</dt>
                <dd>{(content as InfoContent).what}</dd>
              </div>
              {(content as InfoContent).data && (
                <div>
                  <dt className="text-muted-foreground">Dados usados</dt>
                  <dd>{(content as InfoContent).data}</dd>
                </div>
              )}
              {(content as InfoContent).help && (
                <div>
                  <dt className="text-muted-foreground">Como ajuda</dt>
                  <dd>{(content as InfoContent).help}</dd>
                </div>
              )}
            </dl>
          ) : (
            <div className="text-muted-foreground">{content as ReactNode}</div>
          )}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
