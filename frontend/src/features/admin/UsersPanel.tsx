import { Pencil, Search, UserPlus } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Switch } from "@/components/ui/controls";
import { Tooltip } from "@/components/ui/overlays";
import {
  Badge,
  Input,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui/primitives";
import type { User, UserRole } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { USER_ROLE, USER_ROLE_ORDER } from "@/lib/vocabulary";

import { useToggleUserActive, useUsers } from "./api";
import { UserDialog } from "./UserDialog";

const normalize = (text: string) =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

export function UsersPanel() {
  const { user: me } = useAuth();
  const users = useUsers();
  const toggleActive = useToggleUserActive();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<UserRole | null>(null);
  const [showInactive, setShowInactive] = useState(true);
  const [editing, setEditing] = useState<User | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const all = useMemo(() => users.data?.items ?? [], [users.data]);
  const roleCounts = useMemo(() => {
    const counts: Partial<Record<UserRole, number>> = {};
    all.forEach((u) => (counts[u.role] = (counts[u.role] ?? 0) + 1));
    return counts;
  }, [all]);
  const visible = useMemo(() => {
    const term = normalize(q.trim());
    return all.filter(
      (u) =>
        (!role || u.role === role) &&
        (showInactive || u.is_active) &&
        (!term || normalize(`${u.full_name} ${u.email}`).includes(term)),
    );
  }, [all, q, role, showInactive]);
  const inactive = all.filter((u) => !u.is_active).length;

  const openDialog = (user: User | null) => {
    setEditing(user);
    setDialogOpen(true);
  };

  return (
    <section aria-labelledby="usuarios-titulo" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="usuarios-titulo" className="font-semibold">
            Usuários
          </h2>
          <p className="text-sm text-muted-foreground">
            {all.length} cadastrados
            {inactive > 0 && ` · ${inactive} com acesso desativado`}
          </p>
        </div>
        <Button onClick={() => openDialog(null)}>
          <UserPlus /> Novo usuário
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-72">
          <Search
            className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
            aria-hidden
          />
          <Input
            className="pl-8"
            aria-label="Buscar usuário"
            placeholder="Nome ou e-mail"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrar por perfil">
          {USER_ROLE_ORDER.map((r) => (
            <Chip
              key={r}
              pressed={role === r}
              onToggle={() => setRole(role === r ? null : r)}
              count={roleCounts[r] ?? 0}
            >
              {USER_ROLE[r].label}
            </Chip>
          ))}
          <Chip pressed={!showInactive} onToggle={() => setShowInactive((v) => !v)}>
            Só ativos
          </Chip>
        </div>
      </div>

      <div className="rounded-lg border bg-card">
        {users.isLoading ? (
          <Skeleton className="m-4 h-48" />
        ) : visible.length === 0 ? (
          <p className="p-6 text-center text-sm text-muted-foreground">
            Nenhum usuário encontrado com esses filtros.
          </p>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Usuário</TH>
                <TH className="w-48">Perfil</TH>
                <TH className="w-40">Acesso</TH>
                <TH className="hidden w-32 md:table-cell">Desde</TH>
                <TH className="w-12">
                  <span className="sr-only">Ações</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {visible.map((u) => {
                const isSelf = u.id === me?.id;
                const RoleIcon = USER_ROLE[u.role].icon;
                return (
                  <TR key={u.id} className={cn(!u.is_active && "text-muted-foreground")}>
                    <TD>
                      <div className="flex items-center gap-2.5">
                        <span
                          className={cn(
                            "grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/15 text-xs font-bold text-primary",
                            !u.is_active && "bg-muted text-muted-foreground",
                          )}
                          aria-hidden
                        >
                          {initials(u.full_name)}
                        </span>
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 font-medium">
                            <span className="truncate">{u.full_name}</span>
                            {isSelf && <Badge>Você</Badge>}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">{u.email}</div>
                        </div>
                      </div>
                    </TD>
                    <TD>
                      <span className="inline-flex items-center gap-1.5">
                        <RoleIcon className="h-4 w-4 text-muted-foreground" aria-hidden />
                        {USER_ROLE[u.role].label}
                      </span>
                    </TD>
                    <TD>
                      <ActiveSwitch
                        user={u}
                        disabled={isSelf || toggleActive.isPending}
                        reason={isSelf ? "Você não pode desativar o próprio acesso." : undefined}
                        onToggle={() => toggleActive.mutate(u)}
                      />
                    </TD>
                    <TD className="hidden tabular-nums md:table-cell">
                      {formatDate(u.created_at)}
                    </TD>
                    <TD>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Editar ${u.full_name}`}
                        onClick={() => openDialog(u)}
                      >
                        <Pencil />
                      </Button>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </div>

      <UserDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        user={editing}
        isSelf={editing?.id === me?.id}
      />
    </section>
  );
}

function ActiveSwitch({
  user,
  disabled,
  reason,
  onToggle,
}: {
  user: User;
  disabled: boolean;
  reason?: string;
  onToggle: () => void;
}) {
  const id = `ativo-${user.id}`;
  const control = (
    <span className="inline-flex items-center gap-2">
      <Switch
        id={id}
        checked={user.is_active}
        disabled={disabled}
        onCheckedChange={onToggle}
        aria-label={`Acesso de ${user.full_name}`}
      />
      <label htmlFor={id} className="text-xs">
        {user.is_active ? "Ativo" : "Desativado"}
      </label>
    </span>
  );
  return reason ? <Tooltip content={reason}>{control}</Tooltip> : control;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (
    (parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")
  ).toUpperCase();
}
