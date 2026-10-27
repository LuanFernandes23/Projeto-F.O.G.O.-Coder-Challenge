import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChoiceCards } from "@/components/ui/choice-cards";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Input, Label } from "@/components/ui/primitives";
import { fieldErrors } from "@/features/inventory/form-errors";
import { errorMessage } from "@/lib/api/client";
import type {
  OrganizationCreate,
  OrganizationKind,
  OrganizationListItem,
  OrganizationUpdate,
} from "@/lib/api/types";
import { ORGANIZATION_KIND } from "@/lib/vocabulary";

import { useSaveOrganization } from "./api";

const KINDS = Object.keys(ORGANIZATION_KIND) as OrganizationKind[];

/** Cria (organization = null) ou edita um órgão responsável. */
export function OrganizationDialog({
  open,
  onOpenChange,
  organization,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organization: OrganizationListItem | null;
}) {
  const isEdit = Boolean(organization);
  // O cargo dos agentes depende do tipo do órgão: com vínculos, a API não deixa trocar.
  const kindLocked = Boolean(organization?.in_use);
  const [name, setName] = useState("");
  const [acronym, setAcronym] = useState("");
  const [kind, setKind] = useState<OrganizationKind | "">("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setName(organization?.name ?? "");
    setAcronym(organization?.acronym ?? "");
    setKind(organization?.kind ?? "");
    setErrors({});
  }, [open, organization]);

  const save = useSaveOrganization(
    (saved) => {
      toast.success(isEdit ? "Órgão atualizado" : "Órgão cadastrado", {
        description: `${saved.acronym} · ${saved.name}`,
      });
      onOpenChange(false);
    },
    (error) => {
      setErrors(fieldErrors(error));
      toast.error(errorMessage(error));
    },
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (name.trim().length < 3) local.name = "Informe o nome do órgão.";
    if (acronym.trim().length < 2) local.acronym = "Mínimo de 2 letras.";
    if (!kind) local.kind = "Escolha o tipo do órgão.";
    setErrors(local);
    if (Object.keys(local).length) return;

    if (organization) {
      const body: OrganizationUpdate = {
        name: name.trim(),
        acronym: acronym.trim(),
        kind: kindLocked ? undefined : (kind as OrganizationKind),
      };
      save.mutate({ id: organization.id, body });
    } else {
      const body: OrganizationCreate = {
        name: name.trim(),
        acronym: acronym.trim(),
        kind: kind as OrganizationKind,
      };
      save.mutate({ body });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <form onSubmit={submit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{isEdit ? `Editar ${organization?.acronym}` : "Novo órgão"}</DialogTitle>
            <DialogDescription>
              Órgãos são responsáveis por equipamentos e lotam os agentes de campo.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-[1fr_10rem]">
            <div className="space-y-1.5">
              <Label htmlFor="org-name">Nome</Label>
              <Input
                id="org-name"
                autoComplete="off"
                placeholder="Ex.: Secretaria de Mobilidade Urbana"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={Boolean(errors.name)}
              />
              {errors.name && <p className="text-xs text-destructive">{errors.name}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="org-acronym">Sigla</Label>
              <Input
                id="org-acronym"
                autoComplete="off"
                placeholder="Ex.: SEMOB"
                maxLength={20}
                value={acronym}
                onChange={(e) => setAcronym(e.target.value.toUpperCase())}
                aria-invalid={Boolean(errors.acronym)}
              />
              {errors.acronym && <p className="text-xs text-destructive">{errors.acronym}</p>}
            </div>
          </div>

          <fieldset className="space-y-1.5">
            <legend className="mb-1.5 text-sm font-medium">Tipo</legend>
            <ChoiceCards
              label="Tipo do órgão"
              value={kind}
              onChange={setKind}
              invalid={Boolean(errors.kind)}
              choices={KINDS.map((k) => ({
                value: k,
                label: ORGANIZATION_KIND[k].label,
                description: ORGANIZATION_KIND[k].hint,
                icon: ORGANIZATION_KIND[k].icon,
                disabled: kindLocked && k !== organization?.kind,
              }))}
            />
            {kindLocked && (
              <p className="text-xs text-muted-foreground">
                O tipo não pode mudar enquanto houver equipamentos ou agentes vinculados, porque os
                cargos dos agentes dependem dele.
              </p>
            )}
            {errors.kind && <p className="text-xs text-destructive">{errors.kind}</p>}
          </fieldset>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {isEdit ? "Salvar alterações" : "Cadastrar órgão"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
