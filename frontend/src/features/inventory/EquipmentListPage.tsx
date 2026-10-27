import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, MapPin, Plus, Search } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { EquipmentStatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Input, Skeleton, Table, TBody, TD, TH, THead, TR } from "@/components/ui/primitives";
import { useEquipmentTypes, useRegionShapes } from "@/features/operations/api";
import { api } from "@/lib/api/client";
import type { Equipment, Page } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { EQUIPMENT_STATUS, STATUS_ORDER, typeIcon } from "@/lib/vocabulary";

const PAGE_SIZE = 25;

export function EquipmentListPage() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const types = useEquipmentTypes();
  const regions = useRegionShapes();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("");
  const [region, setRegion] = useState("");
  const [offset, setOffset] = useState(0);

  const list = useQuery({
    queryKey: ["equipment-list", { q, type, status, region, offset }],
    queryFn: () =>
      api<Page<Equipment>>("/equipment", {
        query: {
          q: q.length >= 2 ? q : undefined,
          type_code: type || undefined,
          status: status || undefined,
          region_id: region || undefined,
          limit: PAGE_SIZE,
          offset,
        },
      }),
    placeholderData: keepPreviousData,
  });

  const reset =
    <T,>(setter: (v: T) => void) =>
    (value: T) => {
      setter(value);
      setOffset(0);
    };
  const total = list.data?.total ?? 0;

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Inventário de equipamentos</h1>
          <p className="text-sm text-muted-foreground">{total} equipamentos encontrados</p>
        </div>
        {can("equipment:write") && (
          <Button asChild>
            <Link to="/inventario/equipamentos/novo">
              <Plus /> Novo equipamento
            </Link>
          </Button>
        )}
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            className="pl-8"
            aria-label="Buscar"
            placeholder="Série, marca, modelo ou rua"
            value={q}
            onChange={(e) => reset(setQ)(e.target.value)}
          />
        </div>
        <Select
          aria-label="Tipo"
          value={type}
          onValueChange={reset(setType)}
          allowEmpty
          emptyLabel="Todos os tipos"
          options={(types.data ?? []).map((t) => ({ value: t.code, label: t.name }))}
          placeholder="Todos os tipos"
        />
        <Select
          aria-label="Situação"
          value={status}
          onValueChange={reset(setStatus)}
          allowEmpty
          emptyLabel="Todas as situações"
          options={STATUS_ORDER.map((s) => ({ value: s, label: EQUIPMENT_STATUS[s].label }))}
          placeholder="Todas as situações"
        />
        <Select
          aria-label="Região"
          value={region}
          onValueChange={reset(setRegion)}
          allowEmpty
          emptyLabel="Todas as regiões"
          options={(regions.data ?? []).map((r) => ({ value: r.id, label: r.name }))}
          placeholder="Todas as regiões"
        />
      </div>
      <div className="rounded-lg border bg-card">
        {list.isLoading ? (
          <Skeleton className="m-4 h-64" />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Equipamento</TH>
                <TH>Situação</TH>
                <TH className="hidden md:table-cell">Local</TH>
                <TH className="hidden lg:table-cell">Órgão</TH>
                <TH className="hidden lg:table-cell">Próx. manutenção</TH>
                <TH className="w-12">
                  <span className="sr-only">Ações</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {list.data?.items.map((e) => {
                const Icon = typeIcon(e.type.code);
                return (
                  <TR
                    key={e.id}
                    className={can("equipment:write") ? "cursor-pointer" : undefined}
                    onClick={() =>
                      can("equipment:write") && navigate(`/inventario/equipamentos/${e.id}`)
                    }
                  >
                    <TD>
                      <div className="flex items-center gap-2">
                        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
                        <div>
                          <div className="font-medium">{e.serial_number}</div>
                          <div className="text-xs text-muted-foreground">
                            {e.type.name} · {e.brand} {e.model}
                          </div>
                        </div>
                      </div>
                    </TD>
                    <TD>
                      <EquipmentStatusBadge status={e.status} />
                    </TD>
                    <TD className="hidden md:table-cell">
                      <div>{e.address.street}</div>
                      <div className="text-xs text-muted-foreground">
                        {e.address.neighborhood} · {e.region?.name ?? "—"}
                      </div>
                    </TD>
                    <TD className="hidden lg:table-cell">{e.organization.acronym}</TD>
                    <TD className="hidden lg:table-cell">
                      <span
                        className={
                          e.maintenance.is_overdue ? "font-medium text-destructive" : undefined
                        }
                      >
                        {formatDate(e.maintenance.next_maintenance_date)}
                      </span>
                    </TD>
                    <TD>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Ver ${e.serial_number} no mapa`}
                        onClick={(ev) => {
                          ev.stopPropagation();
                          navigate(`/?q=${encodeURIComponent(e.serial_number)}`);
                        }}
                      >
                        <MapPin />
                      </Button>
                    </TD>
                  </TR>
                );
              })}
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
