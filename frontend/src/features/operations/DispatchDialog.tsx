import { Car, Footprints, Navigation, Star, Timer } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DutyBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Skeleton } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/client";
import type { Equipment } from "@/lib/api/types";
import { formatDistance } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ROLE } from "@/lib/vocabulary";

import { useCreateDispatch, useDispatchSuggestions } from "./api";

export function DispatchDialog({
  equipment,
  open,
  onOpenChange,
}: {
  equipment: Equipment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const suggestions = useDispatchSuggestions(equipment.id, open);
  const create = useCreateDispatch();
  const [selected, setSelected] = useState<string | null>(null);
  const chosen = selected ?? suggestions.data?.[0]?.agent_id ?? null;

  const submit = () => {
    if (!chosen) return;
    create.mutate(
      { equipment_id: equipment.id, agent_id: chosen },
      {
        onSuccess: (dispatch) => {
          toast.success(`${dispatch.agent_name} despachado`, {
            description: `Chegada estimada em ${Math.round(dispatch.eta_minutes)} min.`,
          });
          onOpenChange(false);
        },
        onError: (error) => toast.error(errorMessage(error)),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Despachar equipe para {equipment.serial_number}</DialogTitle>
          <DialogDescription>
            Agentes livres e aptos a esta ocorrência, ordenados pelo tempo estimado de chegada
            (distância real calculada no PostGIS × fator de trajeto urbano).
          </DialogDescription>
        </DialogHeader>

        {suggestions.isLoading && <Skeleton className="h-48" />}
        {suggestions.data?.length === 0 && (
          <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
            Nenhum agente apto está livre agora. Tente novamente em instantes.
          </p>
        )}
        <div role="radiogroup" aria-label="Agentes sugeridos" className="space-y-2">
          {suggestions.data?.map((s) => {
            const isChosen = chosen === s.agent_id;
            const Vehicle = s.vehicle_type ? Car : Footprints;
            return (
              <button
                key={s.agent_id}
                type="button"
                role="radio"
                aria-checked={isChosen}
                onClick={() => setSelected(s.agent_id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50",
                  isChosen && "border-primary bg-primary/5 ring-1 ring-primary",
                )}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{s.full_name}</span>
                    {s.recommended && (
                      <span className="inline-flex items-center gap-0.5 rounded bg-primary/15 px-1.5 text-[11px] font-semibold text-primary">
                        <Star className="h-3 w-3" /> recomendado
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>
                      {ROLE[s.role].label} · {s.organization_acronym}
                    </span>
                    <DutyBadge status={s.duty_status} />
                  </div>
                </div>
                <div className="text-right text-xs">
                  <div className="inline-flex items-center gap-1 text-base font-semibold tabular-nums">
                    <Timer className="h-4 w-4 text-primary" /> {Math.round(s.eta_minutes)} min
                  </div>
                  <div className="flex items-center justify-end gap-2 text-muted-foreground">
                    <span className="inline-flex items-center gap-0.5">
                      <Navigation className="h-3 w-3" /> {formatDistance(s.distance_m)}
                    </span>
                    <Vehicle
                      className="h-3.5 w-3.5"
                      aria-label={s.vehicle_type ? "com viatura" : "a pé"}
                    />
                  </div>
                </div>
              </button>
            );
          })}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button onClick={submit} disabled={!chosen || create.isPending}>
            Despachar agora
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
