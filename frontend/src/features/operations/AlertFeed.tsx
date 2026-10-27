import { CheckCheck, Clock, MapPin } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { ToneCard } from "@/components/ui/tone";
import { errorMessage } from "@/lib/api/client";
import type { Alert } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatDuration, fromNow } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SEVERITY } from "@/lib/vocabulary";

import { useAcknowledgeAlert, useAlerts } from "./api";

/** Relógio de 1 s para os cronômetros de SLA (re-renderiza só o feed). */
function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

function SlaTimer({ alert, now }: { alert: Alert; now: number }) {
  const remaining = (new Date(alert.sla_due_at).getTime() - now) / 1000;
  const breached = remaining < 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 tabular-nums",
        breached && "font-semibold text-destructive",
      )}
      title={breached ? "Prazo de atendimento estourado" : "Tempo restante do SLA"}
    >
      <Clock className="h-3 w-3" aria-hidden />
      {breached ? `SLA −${formatDuration(-remaining)}` : `SLA ${formatDuration(remaining)}`}
    </span>
  );
}

export function AlertFeed({ onLocate }: { onLocate: (alert: Alert) => void }) {
  const { can } = useAuth();
  const alerts = useAlerts({ status: ["aberto", "reconhecido"], limit: 100 });
  const acknowledge = useAcknowledgeAlert();
  const now = useNow();

  if (alerts.isLoading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  }
  const items = alerts.data?.items ?? [];
  if (!items.length) {
    return (
      <p className="p-6 text-center text-sm text-muted-foreground">
        Nenhum alerta aberto. A cidade está tranquila.
      </p>
    );
  }

  return (
    <ul className="space-y-2 p-3" aria-live="polite" aria-label="Alertas abertos">
      {items.map((alert) => {
        const severity = SEVERITY[alert.severity];
        const acknowledged = alert.status === "reconhecido";
        return (
          <ToneCard
            as="li"
            key={alert.id}
            tone="neutral"
            color={severity.color}
            glow={!acknowledged && alert.severity === "critica"}
            className={cn("px-3 py-2.5", acknowledged && "opacity-80")}
          >
            <div className="flex items-baseline gap-2 text-[11px]">
              <span className="font-semibold text-[hsl(var(--tone))]">{severity.label}</span>
              <span className="truncate text-muted-foreground">{alert.kind_label}</span>
              {acknowledged && (
                <span className="inline-flex shrink-0 items-center gap-0.5 text-status-ok">
                  <CheckCheck className="h-3 w-3" aria-hidden /> reconhecido
                </span>
              )}
              <span className="ml-auto shrink-0 text-muted-foreground">
                {fromNow(alert.opened_at)}
              </span>
            </div>
            <p className="mt-0.5 truncate text-sm font-medium" title={alert.title}>
              {alert.title}
            </p>
            <p className="truncate text-xs text-muted-foreground" title={alert.description}>
              {alert.description}
            </p>
            <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground">
              <SlaTimer alert={alert} now={now} />
              {alert.region_name && <span className="truncate">{alert.region_name}</span>}
              {alert.occurrences > 1 && <span>{alert.occurrences}×</span>}
              <span className="ml-auto flex shrink-0 gap-1">
                {alert.equipment && (
                  <Button variant="ghost" size="xs" onClick={() => onLocate(alert)}>
                    <MapPin /> Mapa
                  </Button>
                )}
                {!acknowledged && can("alert:acknowledge") && (
                  <Button
                    variant="outline"
                    size="xs"
                    disabled={acknowledge.isPending}
                    onClick={() =>
                      acknowledge.mutate(alert.id, {
                        onSuccess: () => toast.success("Alerta reconhecido"),
                        onError: (e) => toast.error(errorMessage(e)),
                      })
                    }
                  >
                    <CheckCheck /> Reconhecer
                  </Button>
                )}
              </span>
            </div>
          </ToneCard>
        );
      })}
    </ul>
  );
}
