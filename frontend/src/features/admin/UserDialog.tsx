import { Check, Copy, Eye, EyeOff, Wand2 } from "lucide-react";
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
import type { User, UserCreate, UserRole, UserUpdate } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { USER_ROLE, USER_ROLE_ORDER } from "@/lib/vocabulary";

import { useSaveUser } from "./api";
import { generatePassword, passwordStrength, type PasswordStrength } from "./password";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const STRENGTH: Record<PasswordStrength, { label: string; width: string; color: string }> = {
  fraca: { label: "Fraca", width: "w-1/3", color: "bg-status-fault" },
  media: { label: "Média", width: "w-2/3", color: "bg-status-maintenance" },
  forte: { label: "Forte", width: "w-full", color: "bg-status-ok" },
};

/** Cria (user = null) ou edita um usuário. O e-mail é o login e não muda depois de criado. */
export function UserDialog({
  open,
  onOpenChange,
  user,
  isSelf,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: User | null;
  isSelf: boolean;
}) {
  const isEdit = Boolean(user);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole | "">("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [copied, setCopied] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setName(user?.full_name ?? "");
    setEmail(user?.email ?? "");
    setRole(user?.role ?? "");
    setPassword("");
    setShowPassword(false);
    setCopied(false);
    setErrors({});
  }, [open, user]);

  const save = useSaveUser(
    (saved) => {
      toast.success(isEdit ? "Usuário atualizado" : "Usuário cadastrado", {
        description: isEdit
          ? saved.full_name
          : `${saved.full_name} já pode entrar. Envie a senha provisória por um canal seguro.`,
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
    if (name.trim().length < 3) local.full_name = "Informe o nome completo.";
    if (!isEdit && !EMAIL.test(email.trim())) local.email = "Informe um e-mail válido.";
    if (!role) local.role = "Escolha o perfil de acesso.";
    if ((!isEdit || password) && password.length < 8)
      local.password = "A senha precisa de ao menos 8 caracteres.";
    setErrors(local);
    if (Object.keys(local).length) return;

    if (user) {
      const body: UserUpdate = {
        full_name: name.trim() !== user.full_name ? name.trim() : undefined,
        role: !isSelf && role !== user.role ? (role as UserRole) : undefined,
        password: password || undefined,
      };
      save.mutate({ id: user.id, body });
    } else {
      const body: UserCreate = {
        full_name: name.trim(),
        email: email.trim(),
        role: role as UserRole,
        password,
      };
      save.mutate({ body });
    }
  };

  const fillGenerated = () => {
    setPassword(generatePassword());
    setShowPassword(true);
    setCopied(false);
  };

  const copyPassword = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      toast.error("Não foi possível copiar. Selecione a senha e copie manualmente.");
    }
  };

  const strength = password ? STRENGTH[passwordStrength(password)] : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <form onSubmit={submit} noValidate className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{isEdit ? `Editar ${user?.full_name}` : "Novo usuário"}</DialogTitle>
            <DialogDescription>
              {isEdit
                ? "Altere o nome, o perfil ou defina uma nova senha."
                : "Quem vai acessar o F.O.G.O. e o que essa pessoa pode fazer."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="user-name">Nome completo</Label>
              <Input
                id="user-name"
                autoComplete="off"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-invalid={Boolean(errors.full_name)}
              />
              {errors.full_name && <p className="text-xs text-destructive">{errors.full_name}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="user-email">E-mail (login)</Label>
              <Input
                id="user-email"
                type="email"
                autoComplete="off"
                value={email}
                disabled={isEdit}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={Boolean(errors.email)}
                aria-describedby={isEdit ? "user-email-hint" : undefined}
              />
              {isEdit && (
                <p id="user-email-hint" className="text-xs text-muted-foreground">
                  O e-mail é o login e não pode ser alterado.
                </p>
              )}
              {errors.email && <p className="text-xs text-destructive">{errors.email}</p>}
            </div>
          </div>

          <fieldset className="space-y-1.5">
            <legend className="mb-1.5 text-sm font-medium">Perfil de acesso</legend>
            <ChoiceCards
              label="Perfil de acesso"
              value={role}
              onChange={setRole}
              invalid={Boolean(errors.role)}
              choices={USER_ROLE_ORDER.map((r) => ({
                value: r,
                ...USER_ROLE[r],
                disabled: isSelf && r !== user?.role,
              }))}
            />
            {isSelf && (
              <p className="text-xs text-muted-foreground">
                Você não pode alterar o próprio perfil; peça a outro administrador.
              </p>
            )}
            {errors.role && <p className="text-xs text-destructive">{errors.role}</p>}
          </fieldset>

          <div className="space-y-1.5">
            <Label htmlFor="user-password">
              {isEdit ? "Nova senha (deixe em branco para manter)" : "Senha provisória"}
            </Label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  id="user-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="pr-9"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setCopied(false);
                  }}
                  aria-invalid={Boolean(errors.password)}
                  aria-describedby="user-password-strength"
                />
                <button
                  type="button"
                  className="absolute right-1 top-1 grid h-7 w-7 place-items-center rounded text-muted-foreground hover:text-foreground"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <Button type="button" variant="outline" onClick={fillGenerated}>
                <Wand2 /> Gerar
              </Button>
              <Button
                type="button"
                variant="outline"
                size="icon"
                disabled={!password}
                onClick={() => void copyPassword()}
                aria-label={copied ? "Senha copiada" : "Copiar senha"}
              >
                {copied ? <Check className="text-status-ok" /> : <Copy />}
              </Button>
            </div>
            <div id="user-password-strength" className="flex items-center gap-2" aria-live="polite">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                {strength && (
                  <div
                    className={cn(
                      "h-full rounded-full transition-all",
                      strength.width,
                      strength.color,
                    )}
                  />
                )}
              </div>
              <span className="w-28 text-right text-xs text-muted-foreground">
                {strength ? `Senha ${strength.label.toLowerCase()}` : "Mínimo de 8 caracteres"}
              </span>
            </div>
            {errors.password && <p className="text-xs text-destructive">{errors.password}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {isEdit ? "Salvar alterações" : "Cadastrar usuário"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
