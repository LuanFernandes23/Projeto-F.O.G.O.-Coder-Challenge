import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Skeleton,
} from "@/components/ui/primitives";
import { useEquipment, useEquipmentTypes, useOrganizations } from "@/features/operations/api";
import { api, ApiError, errorMessage } from "@/lib/api/client";
import type { Equipment, EquipmentCreate, EquipmentStatus, EquipmentUpdate } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { EQUIPMENT_STATUS } from "@/lib/vocabulary";

import { fieldErrors } from "./form-errors";
import { LocationFields, maskCep, type AddressValue, type PointValue } from "./LocationFields";
import { defaultAttributes, SchemaFields, type JsonSchema } from "./SchemaFields";

const INITIAL_STATUSES: EquipmentStatus[] = [
  "nao_instalado",
  "operacional",
  "mau_funcionamento",
  "desativado",
];
const EMPTY_ADDRESS: AddressValue = {
  cep: "",
  street: "",
  reference: "",
  neighborhood: "",
  city: "Marília",
  uf: "SP",
};

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error && (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function EquipmentFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const existing = useEquipment(id);
  const types = useEquipmentTypes();
  const organizations = useOrganizations();

  const [typeCode, setTypeCode] = useState("");
  const [serial, setSerial] = useState("");
  const [brand, setBrand] = useState("");
  const [model, setModel] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [status, setStatus] = useState<EquipmentStatus>("nao_instalado");
  const [installedOn, setInstalledOn] = useState("");
  const [address, setAddress] = useState<AddressValue>(EMPTY_ADDRESS);
  const [point, setPoint] = useState<PointValue | null>(null);
  const [attributes, setAttributes] = useState<Record<string, unknown>>({});
  const [interval, setInterval] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Edição: carrega os dados atuais uma única vez.
  useEffect(() => {
    const e = existing.data;
    if (!e) return;
    setTypeCode(e.type.code);
    setSerial(e.serial_number);
    setBrand(e.brand);
    setModel(e.model);
    setOrganizationId(e.organization.id);
    setStatus(e.status);
    setInstalledOn(e.installed_on ?? "");
    setAddress({ ...e.address, cep: maskCep(e.address.cep), reference: e.address.reference ?? "" });
    setPoint(e.location);
    setAttributes(e.attributes);
  }, [existing.data]);

  const type = types.data?.find((t) => t.code === typeCode);
  const schema = (type?.attributes_schema ?? {}) as JsonSchema;
  const typeOptions = useMemo(
    () => (types.data ?? []).map((t) => ({ value: t.code, label: t.name })),
    [types.data],
  );

  const save = useMutation({
    mutationFn: async (): Promise<Equipment> => {
      const common = {
        serial_number: serial,
        brand,
        model,
        organization_id: organizationId,
        installed_on: installedOn || null,
        address: { ...address, reference: address.reference || null },
        location: point!,
        attributes,
      };
      if (isEdit && existing.data) {
        const body: EquipmentUpdate = { ...common, version: existing.data.version };
        return api<Equipment>(`/equipment/${id}`, { method: "PATCH", body });
      }
      const body: EquipmentCreate = {
        ...common,
        type_code: typeCode,
        status,
        maintenance_plan: interval ? { interval_days: Number(interval) } : null,
      };
      return api<Equipment>("/equipment", { method: "POST", body });
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["map-features"] });
      void queryClient.invalidateQueries({ queryKey: ["equipment-list"] });
      queryClient.setQueryData(["equipment", saved.id], saved);
      toast.success(isEdit ? "Equipamento atualizado" : "Equipamento cadastrado", {
        description: `${saved.serial_number} · ${saved.region?.name ?? "sem região"}`,
      });
      navigate("/inventario/equipamentos");
    },
    onError: (error) => {
      setErrors(fieldErrors(error));
      if (error instanceof ApiError && error.code === "versao_desatualizada") {
        toast.error("Outra pessoa alterou este equipamento.", {
          action: { label: "Recarregar", onClick: () => void existing.refetch() },
        });
        return;
      }
      toast.error(errorMessage(error));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (!typeCode) local.type_code = "Escolha o tipo.";
    if (!organizationId) local.organization_id = "Escolha o órgão responsável.";
    if (!point) local.location = "Marque a coordenada no mapa.";
    setErrors(local);
    if (Object.keys(local).length === 0) save.mutate();
  };

  if (isEdit && existing.isLoading) return <Skeleton className="m-6 h-[60vh]" />;
  if (!can("equipment:write")) {
    return (
      <p className="p-6 text-sm text-muted-foreground">
        Seu perfil não pode cadastrar ou editar equipamentos.
      </p>
    );
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-5xl space-y-4 p-4" noValidate>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="icon" aria-label="Voltar">
            <Link to="/inventario/equipamentos">
              <ArrowLeft />
            </Link>
          </Button>
          <h1 className="text-lg font-semibold">
            {isEdit ? `Editar ${existing.data?.serial_number}` : "Novo equipamento"}
          </h1>
        </div>
        <Button type="submit" disabled={save.isPending}>
          <Save /> Salvar
        </Button>
      </div>

      <Section
        title="Identificação"
        description="O tipo define as características específicas do equipamento."
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field id="type" label="Tipo" error={errors.type_code}>
            <Select
              id="type"
              value={typeCode}
              disabled={isEdit}
              invalid={Boolean(errors.type_code)}
              onValueChange={(code) => {
                setTypeCode(code);
                const next = types.data?.find((t) => t.code === code);
                setAttributes(next ? defaultAttributes(next.attributes_schema as JsonSchema) : {});
              }}
              options={typeOptions}
              placeholder="Escolha o tipo"
            />
          </Field>
          <Field id="serial" label="Número de série" error={errors.serial_number}>
            <Input
              id="serial"
              required
              value={serial}
              onChange={(e) => setSerial(e.target.value)}
              aria-invalid={Boolean(errors.serial_number)}
            />
          </Field>
          <Field id="org" label="Órgão responsável" error={errors.organization_id}>
            <Select
              id="org"
              value={organizationId}
              onValueChange={setOrganizationId}
              invalid={Boolean(errors.organization_id)}
              options={(organizations.data ?? []).map((o) => ({
                value: o.id,
                label: `${o.acronym} · ${o.name}`,
              }))}
            />
          </Field>
          <Field id="brand" label="Marca" error={errors.brand}>
            <Input id="brand" required value={brand} onChange={(e) => setBrand(e.target.value)} />
          </Field>
          <Field id="model" label="Modelo" error={errors.model}>
            <Input id="model" required value={model} onChange={(e) => setModel(e.target.value)} />
          </Field>
          {!isEdit && (
            <Field id="status" label="Situação inicial">
              <Select
                id="status"
                value={status}
                onValueChange={(v) => setStatus(v as EquipmentStatus)}
                options={INITIAL_STATUSES.map((s) => ({
                  value: s,
                  label: EQUIPMENT_STATUS[s].label,
                }))}
              />
            </Field>
          )}
          <Field id="installed" label="Data de instalação" error={errors.installed_on}>
            <Input
              id="installed"
              type="date"
              value={installedOn}
              onChange={(e) => setInstalledOn(e.target.value)}
            />
          </Field>
          {!isEdit && (
            <Field
              id="interval"
              label="Manutenção periódica (a cada N dias)"
              error={errors.interval_days}
            >
              <Input
                id="interval"
                type="number"
                min={1}
                max={3650}
                placeholder="Opcional"
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
              />
            </Field>
          )}
        </div>
        {isEdit && (
          <p className="mt-3 text-xs text-muted-foreground">
            A situação muda apenas pela Central de Operações (fica registrada no histórico).
          </p>
        )}
      </Section>

      <Section
        title="Localização"
        description="Informe o CEP para preencher o endereço e marque o ponto exato de instalação (ou da base, para equipamentos móveis)."
      >
        <LocationFields
          idPrefix="eq"
          address={address}
          point={point}
          onAddressChange={setAddress}
          onPointChange={setPoint}
          errors={errors}
        />
      </Section>

      {type && (
        <Section
          title={`Características — ${type.name}`}
          description="Campos gerados a partir do schema do tipo (validados no servidor)."
        >
          <SchemaFields
            schema={schema}
            values={attributes}
            onChange={setAttributes}
            errors={errors}
          />
        </Section>
      )}
    </form>
  );
}
