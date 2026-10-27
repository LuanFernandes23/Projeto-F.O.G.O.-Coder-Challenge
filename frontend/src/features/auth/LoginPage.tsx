import { Flame, Loader2, LogIn } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { errorMessage } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";

// Contas de demonstração do seed (só para avaliação local).
const DEMO_ACCOUNTS = [
  { email: "gestor@fogo.dev", label: "Gestor" },
  { email: "operador@fogo.dev", label: "Operador" },
  { email: "consulta@fogo.dev", label: "Consulta" },
  { email: "admin@fogo.dev", label: "Admin" },
];
const DEMO_PASSWORD = "Fogo@2026";
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== "false";

export function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (isAuthenticated) {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const submit = async (event?: FormEvent, credentials?: { email: string; password: string }) => {
    event?.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(credentials?.email ?? email, credentials?.password ?? password);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    // A tela de entrada usa sempre a paleta escura (identidade do Coder Challenge).
    <div className="dark relative isolate grid min-h-dvh place-items-center overflow-hidden bg-[#050b16] p-4 text-foreground">
      <div
        className="absolute inset-0 -z-10 bg-[radial-gradient(80%_60%_at_50%_0%,#0b2a4a_0%,transparent_70%),radial-gradient(60%_50%_at_100%_100%,#06283a_0%,transparent_70%)]"
        aria-hidden
      />
      <img
        src="/brand/coder-challenge-2026.png"
        alt=""
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 -z-10 w-[min(70rem,140vw)] max-w-none -translate-x-1/2 -translate-y-1/2 select-none opacity-[0.07] blur-[1px]"
      />

      <div className="w-full max-w-[22rem]">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-3 grid h-12 w-12 place-items-center rounded-xl border border-white/10 bg-white/[0.04]">
            <Flame className="h-6 w-6 text-[hsl(var(--brand-fire))]" aria-hidden />
          </span>
          <h1 className="text-2xl font-semibold tracking-tight">F.O.G.O.</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Ferramenta Onisciente de Gestão e Operações
          </p>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#0b1626]/70 p-6 shadow-[0_30px_80px_-30px_rgb(0_0_0/0.8)] backdrop-blur-xl">
          <form className="space-y-4" onSubmit={(e) => void submit(e)} noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="email">E-mail</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                required
                className="h-10 bg-black/20"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Senha</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                className="h-10 bg-black/20"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p
                role="alert"
                className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {error}
              </p>
            )}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={loading || !email || !password}
            >
              {loading ? <Loader2 className="animate-spin" /> : <LogIn />} Entrar
            </Button>
          </form>
          {DEMO_MODE && (
            <div className="mt-5 border-t border-white/10 pt-4">
              <p className="mb-2 text-xs text-muted-foreground">Acesso de demonstração</p>
              <div className="grid grid-cols-4 gap-1.5">
                {DEMO_ACCOUNTS.map((account) => (
                  <Button
                    key={account.email}
                    variant="outline"
                    size="xs"
                    className="border-white/10 bg-white/[0.03]"
                    disabled={loading}
                    title={account.email}
                    onClick={() =>
                      void submit(undefined, { email: account.email, password: DEMO_PASSWORD })
                    }
                  >
                    {account.label}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          DSIN Coder Challenge 2026 · Marília-SP
        </p>
      </div>
    </div>
  );
}
