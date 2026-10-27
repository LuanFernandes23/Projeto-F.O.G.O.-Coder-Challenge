import {
  Bell,
  BellOff,
  Boxes,
  CircleHelp,
  Flame,
  LogOut,
  Map as MapIcon,
  MessageSquareText,
  Moon,
  Settings2,
  TrendingUp,
  Sun,
  Users,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/controls";
import { Tooltip } from "@/components/ui/overlays";
import { useLiveEvents, type LiveStatus } from "@/features/operations/use-live-events";
import { PrometheusChat } from "@/features/prometheus/PrometheusChat";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { USER_ROLE } from "@/lib/vocabulary";

const NAV = [
  { to: "/", label: "Central de Operações", icon: MapIcon, end: true },
  { to: "/previsoes", label: "Previsões", icon: TrendingUp },
  { to: "/inventario/equipamentos", label: "Equipamentos", icon: Boxes },
  { to: "/inventario/agentes", label: "Agentes", icon: Users },
  {
    to: "/administracao",
    label: "Administração",
    icon: Settings2,
    // Usuários (admin) ou órgãos (gestor em diante); a API confere a permissão de novo.
    permissions: [
      "user:manage",
      "organization:write",
      "ai:configure",
      "prometheus:manage",
      "knowledge:manage",
    ] as const,
  },
];

const LIVE: Record<LiveStatus, { label: string; color: string; description: string }> = {
  live: {
    label: "Ao vivo",
    color: "bg-status-ok",
    description: "Recebendo eventos da cidade em tempo real",
  },
  connecting: {
    label: "Conectando",
    color: "bg-status-maintenance",
    description: "Conectando ao fluxo de eventos",
  },
  offline: {
    label: "Reconectando",
    color: "bg-status-fault",
    description: "Sem conexão em tempo real; tentando novamente",
  },
};

function readSound(): boolean {
  try {
    return localStorage.getItem("fogo-sound") === "on";
  } catch {
    return false;
  }
}

export function AppShell() {
  const { user, logout, can } = useAuth();
  const { theme, toggle } = useTheme();
  const [sound, setSound] = useState(readSound);
  const [chatOpen, setChatOpen] = useState(false);
  const status = useLiveEvents({ soundEnabled: sound });
  const live = LIVE[status];

  const toggleSound = () => {
    setSound((current) => {
      try {
        localStorage.setItem("fogo-sound", current ? "off" : "on");
      } catch {
        /* preferência só nesta sessão */
      }
      return !current;
    });
  };

  return (
    <div className="flex h-dvh flex-col">
      <a
        href="#conteudo"
        className="sr-only z-[2000] rounded bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-2 focus:top-2"
      >
        Pular para o conteúdo
      </a>
      <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3">
        <div className="flex items-center gap-2 font-semibold tracking-tight">
          <Flame className="h-5 w-5 text-[hsl(var(--brand-fire))]" aria-hidden />
          <span>F.O.G.O.</span>
          <span className="hidden text-xs font-normal text-muted-foreground sm:inline">
            Central de Operações · Marília
          </span>
        </div>
        <nav className="ml-4 flex items-center gap-1" aria-label="Principal">
          {NAV.filter((item) => !item.permissions || item.permissions.some(can)).map(
            ({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                    isActive && "bg-accent text-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4" aria-hidden />
                <span className="hidden md:inline">{label}</span>
              </NavLink>
            ),
          )}
          <Tooltip content="Manual do usuário">
            <NavLink
              to="/ajuda"
              aria-label="Manual do usuário"
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
                  isActive && "bg-accent text-foreground",
                )
              }
            >
              <CircleHelp className="h-4 w-4" aria-hidden />
            </NavLink>
          </Tooltip>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <Tooltip content={live.description}>
            <span
              className="mr-2 flex items-center gap-1.5 text-xs font-medium"
              role="status"
              aria-live="polite"
            >
              <span className="relative flex h-2.5 w-2.5">
                {status === "live" && (
                  <span
                    className={cn(
                      "absolute inline-flex h-full w-full animate-ping rounded-full opacity-60",
                      live.color,
                    )}
                  />
                )}
                <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", live.color)} />
              </span>
              <span className="hidden sm:inline">{live.label}</span>
            </span>
          </Tooltip>
          <Tooltip
            content={
              sound
                ? "Desligar aviso sonoro de alertas críticos"
                : "Ligar aviso sonoro de alertas críticos"
            }
          >
            <Button
              variant="ghost"
              size="icon"
              onClick={toggleSound}
              aria-pressed={sound}
              aria-label="Aviso sonoro"
            >
              {sound ? <Bell /> : <BellOff />}
            </Button>
          </Tooltip>
          <Tooltip content="Pergunte ao PROMETHEUS">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setChatOpen(true)}
              aria-label="Pergunte ao PROMETHEUS"
            >
              <MessageSquareText />
            </Button>
          </Tooltip>
          <Tooltip content={theme === "dark" ? "Tema claro" : "Tema escuro"}>
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Alternar tema">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
          </Tooltip>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="ml-1">
                <span className="grid h-6 w-6 place-items-center rounded-full bg-primary/20 text-xs font-bold text-primary">
                  {user?.full_name.slice(0, 1)}
                </span>
                <span className="hidden max-w-[10rem] truncate lg:inline">{user?.full_name}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                {user?.email}
                <div>Perfil: {user ? USER_ROLE[user.role].label : ""}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={logout}>
                <LogOut /> Sair
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <PrometheusChat open={chatOpen} onOpenChange={setChatOpen} />
      <main id="conteudo" className="min-h-0 flex-1 overflow-auto">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
}
