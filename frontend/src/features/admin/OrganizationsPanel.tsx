import { Boxes, Building2, Lock, Pencil, Plus, Trash2, Users } from "lucide-react";
import { useState } from "react";

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
import { ToneCard, ToneIcon } from "@/components/ui/tone";
import { useOrganizations } from "@/features/operations/api";
import type { OrganizationListItem } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatNumber } from "@/lib/format";
import { ORGANIZATION_KIND } from "@/lib/vocabulary";

import { useDeleteOrganization } from "./api";
import { OrganizationDialog } from "./OrganizationDialog";

export function OrganizationsPanel() {
  const { can } = useAuth();
  const canWrite = can("organization:write");
  const organizations = useOrganizations();
  const [editing, setEditing] = useState<OrganizationListItem | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState<OrganizationListItem | null>(null);
  const remove = useDeleteOrganization(() => setDeleting(null));

  const items = organizations.data ?? [];
  const openDialog = (organization: OrganizationListItem | null) => {
    setEditing(organization);
    setDialogOpen(true);
  };

  return (
    <section aria-labelledby="orgaos-titulo" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="orgaos-titulo" className="font-semibold">
            Órgãos responsáveis
          </h2>
          <p className="text-sm text-muted-foreground">
            {items.length} cadastrados · respondem pelos equipamentos e lotam os agentes
          </p>
        </div>
        {canWrite && (
          <Button onClick={() => openDialog(null)}>
            <Plus /> Novo órgão
          </Button>
        )}
      </div>

      {organizations.isLoading ? (
        <Skeleton className="h-40" />
      ) : items.length === 0 ? (
        <div className="grid place-items-center gap-2 rounded-lg border border-dashed p-10 text-center">
          <Building2 className="h-6 w-6 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">Nenhum órgão cadastrado ainda.</p>
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((o) => {
            const kind = ORGANIZATION_KIND[o.kind];
            return (
              <ToneCard key={o.id} as="li" tone="info" className="flex flex-col gap-3 p-4">
                <div className="flex items-start gap-3">
                  <ToneIcon icon={kind.icon} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-2">
                      <span className="text-base font-semibold">{o.acronym}</span>
                      <span className="text-xs text-muted-foreground">{kind.label}</span>
                    </div>
                    <p className="line-clamp-2 text-sm" title={o.name}>
                      {o.name}
                    </p>
                  </div>
                </div>
                <dl className="flex gap-4 text-sm">
                  <div className="flex items-center gap-1.5">
                    <Boxes className="h-4 w-4 text-muted-foreground" aria-hidden />
                    <dt className="sr-only">Equipamentos</dt>
                    <dd>
                      <span className="font-semibold tabular-nums">
                        {formatNumber(o.equipment_count)}
                      </span>{" "}
                      <span className="text-muted-foreground">equipamentos</span>
                    </dd>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Users className="h-4 w-4 text-muted-foreground" aria-hidden />
                    <dt className="sr-only">Agentes</dt>
                    <dd>
                      <span className="font-semibold tabular-nums">
                        {formatNumber(o.agent_count)}
                      </span>{" "}
                      <span className="text-muted-foreground">agentes</span>
                    </dd>
                  </div>
                </dl>
                {canWrite && (
                  <div className="mt-auto flex items-center gap-1 border-t pt-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Editar ${o.acronym}`}
                      onClick={() => openDialog(o)}
                    >
                      <Pencil /> Editar
                    </Button>
                    {o.in_use ? (
                      <span
                        className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground"
                        title="Órgãos com equipamentos ou agentes vinculados não podem ser excluídos."
                      >
                        <Lock className="h-3.5 w-3.5" aria-hidden /> Em uso
                      </span>
                    ) : (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="ml-auto text-destructive hover:text-destructive"
                        aria-label={`Excluir ${o.acronym}`}
                        onClick={() => setDeleting(o)}
                      >
                        <Trash2 /> Excluir
                      </Button>
                    )}
                  </div>
                )}
              </ToneCard>
            );
          })}
        </ul>
      )}

      <OrganizationDialog open={dialogOpen} onOpenChange={setDialogOpen} organization={editing} />

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Excluir {deleting?.acronym}?</DialogTitle>
            <DialogDescription>
              {deleting?.name} será removido. O órgão não tem equipamentos nem agentes vinculados.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleting && remove.mutate(deleting)}
            >
              Excluir órgão
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
