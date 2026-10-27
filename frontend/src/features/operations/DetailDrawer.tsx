import { Building2, Clock, MapPin, Pencil, Radio, Send, Truck, User, Wrench } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { DutyBadge, EquipmentStatusBadge, SeverityBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Sheet } from "@/components/ui/overlays";
import { Label, Separator, Skeleton, Textarea } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/client";
import type { EquipmentStatus, EquipmentType, MapAgent, MapEquipment } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime, fromNow } from "@/lib/format";
import { EQUIPMENT_STATUS, ROLE } from "@/lib/vocabulary";

import {
  useAlerts,
  useChangeEquipmentStatus,
  useDispatches,
  useEquipment,
  useEquipmentHistory,
  useEquipmentOrders,
  useEquipmentTypes,
  useStatusCatalog,
  useTransitionDispatch,
  useTransitionOrder,
} from "./api";
import { DispatchDialog } from "./DispatchDialog";
import type { Selection } from "./map/CityMap";

function Row({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="mt-0.5 text-muted-foreground" aria-hidden>
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="break-words">{children}</div>
      </div>
    </div>
  );
}

function attributeEntries(attributes: Record<string, unknown>, type: EquipmentType | undefined) {
  const schema = (type?.attributes_schema ?? {}) as {
    properties?: Record<
      string,
      { title?: string; $ref?: string; items?: { $ref?: string }; anyOf?: { $ref?: string }[] }
    >;
    $defs?: Record<string, { "x-enum-labels"?: Record<string, string> }>;
  };
  const labelsFor = (ref?: string) =>
    ref ? schema.$defs?.[ref.split("/").pop() ?? ""]?.["x-enum-labels"] : undefined;
  return Object.entries(attributes)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => {
      const prop = schema.properties?.[key];
      const labels = labelsFor(
        prop?.$ref ?? prop?.items?.$ref ?? prop?.anyOf?.find((a) => a.$ref)?.$ref,
      );
      const show = (v: unknown) =>
        typeof v === "boolean" ? (v ? "Sim" : "Não") : (labels?.[String(v)] ?? String(v));
      return {
        key,
        label: prop?.title ?? key.replaceAll("_", " "),
        value: Array.isArray(value) ? value.map(show).join(", ") : show(value),
      };
    });
}

function EquipmentDetail({ id }: { id: string }) {
  const { can } = useAuth();
  const equipment = useEquipment(id);
  const history = useEquipmentHistory(id);
  const orders = useEquipmentOrders(id);
  const alerts = useAlerts({ equipmentId: id, status: ["aberto", "reconhecido"] });
  const catalog = useStatusCatalog();
  const types = useEquipmentTypes();
  const changeStatus = useChangeEquipmentStatus(id);
  const transitionOrder = useTransitionOrder(id);
  const dispatches = useDispatches();
  const transitionDispatch = useTransitionDispatch();
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [dispatchOpen, setDispatchOpen] = useState(false);

  if (!equipment.data) return <Skeleton className="m-4 h-96" />;
  const e = equipment.data;
  const type = types.data?.find((t) => t.code === e.type.code);
  const transitions =
    (catalog.data?.find((s) => s.code === e.status)?.allowed_transitions ?? []).map((code) => ({
      value: code,
      label: EQUIPMENT_STATUS[code as EquipmentStatus]?.label ?? code,
    })) ?? [];
  const openOrders = (orders.data?.items ?? []).filter(
    (o) => o.status === "aberta" || o.status === "em_andamento",
  );
  const activeDispatch = dispatches.data?.find((d) => d.equipment_id === e.id);
  const canDispatch =
    can("dispatch:manage") &&
    !activeDispatch &&
    ["mau_funcionamento", "furtado", "em_manutencao"].includes(e.status);

  const submitStatus = () =>
    changeStatus.mutate(
      { to_status: target as EquipmentStatus, reason },
      {
        onSuccess: () => {
          toast.success("Situação atualizada");
          setTarget("");
          setReason("");
        },
        onError: (error) => toast.error(errorMessage(error)),
      },
    );

  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <EquipmentStatusBadge status={e.status} />
        {e.maintenance.need === "imediata" && (
          <span className="rounded bg-status-maintenance/15 px-1.5 py-0.5 text-[11px] font-semibold text-status-maintenance">
            Reparo imediato
          </span>
        )}
        {e.maintenance.is_overdue && (
          <span className="rounded bg-destructive/15 px-1.5 py-0.5 text-[11px] font-semibold text-destructive">
            Manutenção vencida
          </span>
        )}
      </div>

      {canDispatch && (
        <Button className="w-full" onClick={() => setDispatchOpen(true)}>
          <Send /> Despachar equipe mais próxima
        </Button>
      )}
      <DispatchDialog equipment={e} open={dispatchOpen} onOpenChange={setDispatchOpen} />
      {activeDispatch && (
        <section
          className="rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm"
          aria-live="polite"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-medium">
              <Send className="mr-1 inline h-4 w-4 text-primary" />
              {activeDispatch.agent_name}
            </span>
            <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] font-semibold text-primary">
              {activeDispatch.status_label}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {ROLE[activeDispatch.agent_role].short} · {activeDispatch.organization_acronym} ·
            despachado {fromNow(activeDispatch.created_at)}
            {activeDispatch.arrived_at && ` · chegou ${fromNow(activeDispatch.arrived_at)}`}
          </p>
          {can("dispatch:manage") && (
            <div className="mt-2 flex gap-2">
              {activeDispatch.status === "no_local" && (
                <Button
                  size="sm"
                  onClick={() =>
                    transitionDispatch.mutate(
                      { id: activeDispatch.id, status: "concluido" },
                      {
                        onSuccess: () => toast.success("Atendimento concluído"),
                        onError: (err) => toast.error(errorMessage(err)),
                      },
                    )
                  }
                >
                  Concluir atendimento
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  transitionDispatch.mutate(
                    { id: activeDispatch.id, status: "cancelado" },
                    {
                      onSuccess: () => toast("Despacho cancelado"),
                      onError: (err) => toast.error(errorMessage(err)),
                    },
                  )
                }
              >
                Cancelar despacho
              </Button>
            </div>
          )}
        </section>
      )}

      <div className="grid gap-3">
        <Row icon={<Building2 className="h-4 w-4" />} label="Órgão responsável">
          {e.organization.acronym} · {e.organization.name}
        </Row>
        <Row icon={<MapPin className="h-4 w-4" />} label="Localização">
          {e.address.street}
          {e.address.reference ? `, ${e.address.reference}` : ""} — {e.address.neighborhood},{" "}
          {e.address.city}/{e.address.uf}
          <div className="text-xs text-muted-foreground">
            {e.region?.name ?? "Sem região"} · {e.location.latitude.toFixed(5)},{" "}
            {e.location.longitude.toFixed(5)}
          </div>
        </Row>
        <Row icon={<Wrench className="h-4 w-4" />} label="Manutenção">
          {e.maintenance.next_maintenance_date
            ? `Próxima em ${formatDate(e.maintenance.next_maintenance_date)}`
            : "Sem plano"}
          {e.maintenance.plan && (
            <span className="text-muted-foreground">
              {" "}
              · a cada {e.maintenance.plan.interval_days} dias
            </span>
          )}
        </Row>
        <Row icon={<Clock className="h-4 w-4" />} label="Instalação">
          {formatDate(e.installed_on)} · {e.brand} {e.model}
        </Row>
      </div>

      {Object.keys(e.attributes).length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-foreground">Características</h3>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
            {attributeEntries(e.attributes, type).map((a) => (
              <div key={a.key} className="min-w-0">
                <dt className="truncate text-[11px] text-muted-foreground">{a.label}</dt>
                <dd className="truncate">{a.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {(alerts.data?.items.length ?? 0) > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-foreground">Alertas abertos</h3>
          <ul className="space-y-1.5">
            {alerts.data?.items.map((a) => (
              <li key={a.id} className="flex items-center gap-2 text-sm">
                <SeverityBadge severity={a.severity} />
                <span className="truncate">{a.kind_label}</span>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {fromNow(a.opened_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {openOrders.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-medium text-foreground">Ordens de manutenção</h3>
          <ul className="space-y-2">
            {openOrders.map((o) => (
              <li key={o.id} className="rounded-md border p-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium capitalize">
                    {o.kind} · {o.priority}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {o.status.replace("_", " ")}
                  </span>
                </div>
                <p className="line-clamp-2 text-xs text-muted-foreground">{o.description}</p>
                {can("maintenance:order_operate") && (
                  <div className="mt-2 flex gap-2">
                    {o.status === "aberta" && (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          transitionOrder.mutate(
                            { orderId: o.id, status: "em_andamento" },
                            {
                              onSuccess: () => toast.success("Reparo iniciado"),
                              onError: (err) => toast.error(errorMessage(err)),
                            },
                          )
                        }
                      >
                        Iniciar reparo
                      </Button>
                    )}
                    {o.status === "em_andamento" && (
                      <Button
                        size="sm"
                        onClick={() =>
                          transitionOrder.mutate(
                            { orderId: o.id, status: "concluida" },
                            {
                              onSuccess: () => toast.success("Reparo concluído"),
                              onError: (err) => toast.error(errorMessage(err)),
                            },
                          )
                        }
                      >
                        Concluir reparo
                      </Button>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {can("equipment:status_change") && transitions.length > 0 && (
        <section className="space-y-2 rounded-lg border p-3">
          <h3 className="text-sm font-medium text-foreground">Mudar situação</h3>
          <Select
            aria-label="Nova situação"
            value={target}
            onValueChange={setTarget}
            options={transitions}
            placeholder="Escolha a nova situação"
          />
          <Label htmlFor="reason" className="sr-only">
            Motivo
          </Label>
          <Textarea
            id="reason"
            placeholder="Motivo (fica registrado no histórico)"
            value={reason}
            onChange={(ev) => setReason(ev.target.value)}
          />
          <Button
            size="sm"
            className="w-full"
            disabled={!target || reason.trim().length < 3 || changeStatus.isPending}
            onClick={submitStatus}
          >
            Registrar mudança
          </Button>
        </section>
      )}

      <Separator />
      <section>
        <h3 className="mb-2 text-sm font-medium text-foreground">Histórico recente</h3>
        <ol className="relative space-y-3 border-l pl-4">
          {history.data?.items.map((h) => (
            <li key={h.id} className="text-sm">
              <span
                className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full"
                style={{ background: `hsl(${EQUIPMENT_STATUS[h.to_status].color})` }}
                aria-hidden
              />
              <div className="font-medium">{h.to_status_label}</div>
              <div className="text-xs text-muted-foreground">
                {formatDateTime(h.changed_at)}
                {h.changed_by_name ? ` · ${h.changed_by_name}` : " · sistema"}
              </div>
              {h.reason && <div className="text-xs">{h.reason}</div>}
            </li>
          ))}
        </ol>
      </section>

      {can("equipment:write") && (
        <Button asChild variant="outline" size="sm" className="w-full">
          <Link to={`/inventario/equipamentos/${e.id}`}>
            <Pencil /> Editar cadastro
          </Link>
        </Button>
      )}
    </div>
  );
}

function AgentDetail({ agent }: { agent: MapAgent }) {
  const Role = ROLE[agent.role].icon;
  return (
    <div className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <DutyBadge status={agent.duty_status} />
        {agent.dispatch_status && (
          <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[11px] font-semibold text-primary">
            Despacho: {agent.dispatch_status.replace("_", " ")}
          </span>
        )}
      </div>
      <Row icon={<Role className="h-4 w-4" />} label="Cargo">
        {ROLE[agent.role].label}
      </Row>
      <Row icon={<Truck className="h-4 w-4" />} label="Deslocamento">
        {agent.vehicle_type === "viatura"
          ? "Viatura"
          : agent.vehicle_type === "moto_agente"
            ? "Motocicleta"
            : "A pé"}
      </Row>
      <Row icon={<Radio className="h-4 w-4" />} label="Posição">
        {agent.live
          ? `GPS ao vivo · atualizado ${fromNow(agent.last_position_at)}`
          : "Sem GPS recente — exibido na base"}
        <div className="text-xs text-muted-foreground">
          {agent.lat.toFixed(5)}, {agent.lng.toFixed(5)}
        </div>
      </Row>
      <Row icon={<User className="h-4 w-4" />} label="Dados pessoais">
        <span className="text-xs text-muted-foreground">
          Apenas dados operacionais mínimos são exibidos (LGPD).
        </span>
      </Row>
    </div>
  );
}

export function DetailDrawer({
  selection,
  equipment,
  agents,
  onClose,
}: {
  selection: Selection;
  equipment: MapEquipment[];
  agents: MapAgent[];
  onClose: () => void;
}) {
  const feature =
    selection?.kind === "equipment" ? equipment.find((e) => e.id === selection.id) : undefined;
  const agent = selection?.kind === "agent" ? agents.find((a) => a.id === selection.id) : undefined;
  const title = feature ? feature.serial_number : agent ? agent.full_name : "Detalhes";
  const description = feature
    ? `${EQUIPMENT_STATUS[feature.status].label} · ${feature.neighborhood}`
    : agent
      ? ROLE[agent.role].label
      : undefined;
  return (
    <Sheet
      open={Boolean(selection)}
      onOpenChange={(open) => !open && onClose()}
      title={title}
      description={description}
    >
      {selection?.kind === "equipment" && <EquipmentDetail id={selection.id} />}
      {agent && <AgentDetail agent={agent} />}
    </Sheet>
  );
}
