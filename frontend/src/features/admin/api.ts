// Consultas e mutações da Administração (usuários e órgãos responsáveis).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage } from "@/lib/api/client";
import type {
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  Page,
  User,
  UserCreate,
  UserUpdate,
} from "@/lib/api/types";

// A equipe de uma prefeitura cabe numa página; a busca e o filtro rodam no cliente.
const USERS_LIMIT = 500;

export const useUsers = () =>
  useQuery({
    queryKey: ["users"],
    queryFn: () => api<Page<User>>("/users", { query: { limit: USERS_LIMIT } }),
  });

export function useSaveUser(onSaved: (user: User) => void, onError: (error: unknown) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: UserCreate | UserUpdate }) =>
      id
        ? api<User>(`/users/${id}`, { method: "PATCH", body })
        : api<User>("/users", { method: "POST", body }),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      onSaved(user);
    },
    onError,
  });
}

/** Ativa/desativa direto da lista; a API impede desativar a si mesmo e o último administrador. */
export function useToggleUserActive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (user: User) =>
      api<User>(`/users/${user.id}`, {
        method: "PATCH",
        body: { is_active: !user.is_active } satisfies UserUpdate,
      }),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(user.is_active ? "Acesso reativado" : "Acesso desativado", {
        description: user.full_name,
      });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}

export function useSaveOrganization(
  onSaved: (organization: Organization) => void,
  onError: (error: unknown) => void,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id?: string; body: OrganizationCreate | OrganizationUpdate }) =>
      id
        ? api<Organization>(`/organizations/${id}`, { method: "PATCH", body })
        : api<Organization>("/organizations", { method: "POST", body }),
    onSuccess: (organization) => {
      void queryClient.invalidateQueries({ queryKey: ["organizations"] });
      onSaved(organization);
    },
    onError,
  });
}

export function useDeleteOrganization(onDeleted: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (organization: Organization) =>
      api<void>(`/organizations/${organization.id}`, { method: "DELETE" }),
    onSuccess: (_, organization) => {
      void queryClient.invalidateQueries({ queryKey: ["organizations"] });
      toast.success("Órgão excluído", { description: organization.name });
      onDeleted();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
}
