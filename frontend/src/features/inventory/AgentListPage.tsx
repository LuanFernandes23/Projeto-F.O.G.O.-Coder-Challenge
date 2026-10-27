import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { DutyBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Input, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { useOrganizations } from "@/features/operations/api";
import { api } from "@/lib/api/client";
import type { Agent, Page } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { ROLE } from "@/lib/vocabulary";

const PAGE_SIZE = 25;

export function AgentListPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const organizations = useOrganizations();
  const [q, setQ] = useState("");
  const [organization, setOrganization] = useState("");
  const [onDuty, setOnDuty] = useState("");
  const [offset, setOffset] = useState(0);

  const list = useQuery({
    queryKey: ["agent-list", { q, organization, onDuty, offset }],
    queryFn: () =>
      api<Page<Agent>>("/agents", {
        query: {
          q: q.length >= 2 ? q : undefined,
          organization_id: organization || undefined,
          on_duty: onDuty === "" ? undefined : onDuty === "sim",
          limit: PAGE_SIZE,
          offset,
        },
      }),
    placeholderData: keepPreviousData,
  });
  const total = list.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Agentes de campo</h1>
          <p className="text-sm text-muted-foreground">{total} agentes encontrados</p>
        </div>
        {can("agent:write") && (
          <Button asChild>
            <Link to="/inventario/agentes/novo">
              <Plus /> Novo agente
            </Link>
          </Button>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            className="pl-8"
            aria-label="Buscar"
            placeholder="Nome ou matrícula"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </div>
        <Select
          aria-label="Órgão"
          value={organization}
          onValueChange={(v) => {
            setOrganization(v);
            setOffset(0);
          }}
          allowEmpty
          emptyLabel="Todos os órgãos"
          placeholder="Todos os órgãos"
          options={(organizations.data ?? []).map((o) => ({
            value: o.id,
            label: `${o.acronym} · ${o.name}`,
          }))}
        />
        <Select
          aria-label="Em serviço"
          value={onDuty}
          onValueChange={(v) => {
            setOnDuty(v);
            setOffset(0);
          }}
          allowEmpty
          emptyLabel="Em serviço ou não"
          placeholder="Em serviço ou não"
          options={[
            { value: "sim", label: "Em atividade" },
            { value: "nao", label: "Fora de atividade" },
          ]}
        />
      </div>
      <div className="rounded-lg border bg-card">
        {list.isLoading ? (
          <Skeleton className="m-4 h-64" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Agente</TH>
                <TH>Situação</TH>
                <TH className="hidden md:table-cell">Órgão</TH>
                <TH className="hidden md:table-cell">Viatura</TH>
                <TH className="hidden lg:table-cell">Região da base</TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.items.map((a) => (
                <TR
                  key={a.id}
                  className={can("agent:write") ? "cursor-pointer" : undefined}
                  onClick={() => can("agent:write") && navigate(`/inventario/agentes/${a.id}`)}
                >
                  <TD>
                    <div className="font-medium">{a.full_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {ROLE[a.role].label} · {a.registration_number}
                    </div>
                  </TD>
                  <TD>
                    <DutyBadge status={a.duty_status} />
                  </TD>
                  <TD className="hidden md:table-cell">{a.organization.acronym}</TD>
                  <TD className="hidden md:table-cell">
                    {a.vehicle
                      ? `${a.vehicle.plate ?? a.vehicle.serial_number} · ${a.vehicle.model}`
                      : "—"}
                  </TD>
                  <TD className="hidden lg:table-cell">{a.region?.name ?? "—"}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
      <div className="flex items-center justify-end gap-2 text-sm">
        <span className="text-muted-foreground">
          {total
            ? `${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} de ${total}`
            : "0 resultados"}
        </span>
        <Button
          variant="outline"
          size="icon"
          aria-label="Página anterior"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        >
          <ChevronLeft />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="Próxima página"
          disabled={offset + PAGE_SIZE >= total}
          onClick={() => setOffset(offset + PAGE_SIZE)}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
