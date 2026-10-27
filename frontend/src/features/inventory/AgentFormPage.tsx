import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Save } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Skeleton,
} from "@/components/ui/primitives";
import { useOrganizations } from "@/features/operations/api";
import { api, errorMessage } from "@/lib/api/client";
import type { Agent, AgentCreate, AgentRole, AgentUpdate, Equipment, Page } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { ROLE } from "@/lib/vocabulary";

import { fieldErrors } from "./form-errors";
import { LocationFields, maskCep, type AddressValue, type PointValue } from "./LocationFields";

const ROLE_BY_KIND: Record<string, AgentRole[]> = {
  transito: ["agente_transito", "outro"],
  guarda_municipal: ["guarda_municipal", "outro"],
  policia_militar: ["policial_militar", "outro"],
};

export function AgentFormPage() {
  const { id } = useParams();
  const isEdit = Boolean(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const organizations = useOrganizations();
  const existing = useQuery({
    queryKey: ["agent", id],
    queryFn: () => api<Agent>(`/agents/${id}`),
    enabled: isEdit,
  });

  const [name, setName] = useState("");
  const [registration, setRegistration] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [role, setRole] = useState<AgentRole | "">("");
  const [vehicleId, setVehicleId] = useState("");
  const [address, setAddress] = useState<AddressValue>({
    cep: "",
    street: "",
    reference: "",
    neighborhood: "",
    city: "Marília",
    uf: "SP",
  });
  const [point, setPoint] = useState<PointValue | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const a = existing.data;
    if (!a) return;
    setName(a.full_name);
    setRegistration(a.registration_number);
    setOrganizationId(a.organization.id);
    setRole(a.role);
    setVehicleId(a.vehicle?.id ?? "");
    setAddress({
      ...a.base_address,
      cep: maskCep(a.base_address.cep),
      reference: a.base_address.reference ?? "",
    });
    setPoint(a.base_location);
  }, [existing.data]);

  const organization = organizations.data?.find((o) => o.id === organizationId);
  const roles = organization
    ? (ROLE_BY_KIND[organization.kind] ?? (Object.keys(ROLE) as AgentRole[]))
    : [];

  const vehicles = useQuery({
    queryKey: ["vehicles", organizationId],
    queryFn: () =>
      api<Page<Equipment>>("/equipment", {
        query: {
          organization_id: organizationId,
          type_code: ["moto_agente", "viatura"],
          limit: 200,
        },
      }),
    enabled: Boolean(organizationId),
  });

  const save = useMutation({
    mutationFn: async (): Promise<Agent> => {
      const base = {
        full_name: name,
        registration_number: registration,
        role: role as AgentRole,
        organization_id: organizationId,
        base_address: { ...address, reference: address.reference || null },
        base_location: point!,
      };
      if (isEdit && existing.data) {
        const body: AgentUpdate = {
          ...base,
          version: existing.data.version,
          assigned_vehicle_id: vehicleId || null,
          unassign_vehicle: !vehicleId && Boolean(existing.data.vehicle),
        };
        return api<Agent>(`/agents/${id}`, { method: "PATCH", body });
      }
      const body: AgentCreate = {
        ...base,
        duty_status: "fora_de_servico",
        assigned_vehicle_id: vehicleId || null,
      };
      return api<Agent>("/agents", { method: "POST", body });
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["agent-list"] });
      void queryClient.invalidateQueries({ queryKey: ["map-features"] });
      toast.success(isEdit ? "Agente atualizado" : "Agente cadastrado", {
        description: saved.full_name,
      });
      navigate("/inventario/agentes");
    },
    onError: (error) => {
      setErrors(fieldErrors(error));
      toast.error(errorMessage(error));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (!organizationId) local.organization_id = "Escolha o órgão.";
    if (!role) local.role = "Escolha o cargo.";
    if (!point) local.location = "Marque a base no mapa.";
    setErrors(local);
    if (!Object.keys(local).length) save.mutate();
  };

  if (isEdit && existing.isLoading) return <Skeleton className="m-6 h-[60vh]" />;
  if (!can("agent:write"))
    return (
      <p className="p-6 text-sm text-muted-foreground">Seu perfil não pode cadastrar agentes.</p>
    );

  return (
    <form onSubmit={submit} className="mx-auto max-w-5xl space-y-4 p-4" noValidate>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="icon" aria-label="Voltar">
            <Link to="/inventario/agentes">
              <ArrowLeft />
            </Link>
          </Button>
          <h1 className="text-lg font-semibold">
            {isEdit ? `Editar ${existing.data?.full_name}` : "Novo agente"}
          </h1>
        </div>
        <Button type="submit" disabled={save.isPending}>
          <Save /> Salvar
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Dados operacionais</CardTitle>
          <p className="text-xs text-muted-foreground">
            Somente o necessário à operação (LGPD): sem CPF, telefone ou endereço pessoal.
          </p>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="name">Nome completo</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={Boolean(errors.full_name)}
            />
            {errors.full_name && <p className="text-xs text-destructive">{errors.full_name}</p>}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="registration">Matrícula</Label>
            <Input
              id="registration"
              value={registration}
              onChange={(e) => setRegistration(e.target.value)}
              aria-invalid={Boolean(errors.registration_number)}
            />
            {errors.registration_number && (
              <p className="text-xs text-destructive">{errors.registration_number}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="organization">Órgão</Label>
            <Select
              id="organization"
              value={organizationId}
              invalid={Boolean(errors.organization_id)}
              onValueChange={(v) => {
                setOrganizationId(v);
                setRole("");
                setVehicleId("");
              }}
              options={(organizations.data ?? [])
                .filter((o) => o.kind !== "concessionaria")
                .map((o) => ({ value: o.id, label: `${o.acronym} · ${o.name}` }))}
            />
            {errors.organization_id && (
              <p className="text-xs text-destructive">{errors.organization_id}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="role">Cargo</Label>
            <Select
              id="role"
              value={role}
              disabled={!organizationId}
              invalid={Boolean(errors.role)}
              onValueChange={(v) => setRole(v as AgentRole)}
              options={roles.map((r) => ({ value: r, label: ROLE[r].label }))}
              placeholder="Escolha o órgão primeiro"
            />
            {errors.role && <p className="text-xs text-destructive">{errors.role}</p>}
          </div>
          <div className="space-y-1.5 lg:col-span-2">
            <Label htmlFor="vehicle">Viatura / moto (opcional)</Label>
            <Select
              id="vehicle"
              value={vehicleId}
              disabled={!organizationId}
              allowEmpty
              emptyLabel="Sem viatura (a pé)"
              placeholder="Sem viatura (a pé)"
              onValueChange={setVehicleId}
              options={(vehicles.data?.items ?? []).map((v) => ({
                value: v.id,
                label: `${String(v.attributes.plate ?? v.serial_number)} · ${v.model} (${v.status_label})`,
              }))}
            />
            {errors.assigned_vehicle_id && (
              <p className="text-xs text-destructive">{errors.assigned_vehicle_id}</p>
            )}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Base de lotação</CardTitle>
        </CardHeader>
        <CardContent>
          <LocationFields
            idPrefix="ag"
            address={address}
            point={point}
            onAddressChange={setAddress}
            onPointChange={setPoint}
            errors={errors}
          />
        </CardContent>
      </Card>
    </form>
  );
}
