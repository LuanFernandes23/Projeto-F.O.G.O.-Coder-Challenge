// Linguagem visual única do sistema: rótulo + cor + ícone para cada estado.
// Nunca usamos só cor para transmitir informação (acessibilidade / daltonismo).
import {
  AlertTriangle,
  Ban,
  BadgeCheck,
  Briefcase,
  Building2,
  Camera,
  CarFront,
  CircleDashed,
  CircleHelp,
  Eye,
  Gauge,
  Hand,
  Headset,
  Shield,
  Monitor,
  Bike,
  Radar,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Siren,
  TrafficCone,
  Wrench,
  Bot,
  BusFront,
  Zap,
  type LucideIcon,
} from "lucide-react";

import type {
  AgentRole,
  AlertSeverity,
  DutyStatus,
  EquipmentStatus,
  HealthLevel,
  OrganizationKind,
  UserRole,
} from "@/lib/api/types";

interface Visual {
  label: string;
  color: string; // variável CSS (hsl) usada no mapa e nos badges
  icon: LucideIcon;
}

export const EQUIPMENT_STATUS: Record<EquipmentStatus, Visual> = {
  operacional: { label: "Operacional", color: "var(--status-ok)", icon: BadgeCheck },
  mau_funcionamento: {
    label: "Mau funcionamento",
    color: "var(--status-fault)",
    icon: AlertTriangle,
  },
  em_manutencao: { label: "Em manutenção", color: "var(--status-maintenance)", icon: Wrench },
  desativado: { label: "Desativado", color: "var(--status-disabled)", icon: Ban },
  furtado: { label: "Furtado", color: "var(--status-stolen)", icon: ShieldAlert },
  nao_instalado: {
    label: "Ainda não instalado",
    color: "var(--status-pending)",
    icon: CircleDashed,
  },
};

export const STATUS_ORDER: EquipmentStatus[] = [
  "operacional",
  "mau_funcionamento",
  "em_manutencao",
  "furtado",
  "desativado",
  "nao_instalado",
];

export const SEVERITY: Record<AlertSeverity, { label: string; color: string; rank: number }> = {
  critica: { label: "Crítica", color: "var(--sev-critica)", rank: 4 },
  alta: { label: "Alta", color: "var(--sev-alta)", rank: 3 },
  media: { label: "Média", color: "var(--sev-media)", rank: 2 },
  baixa: { label: "Baixa", color: "var(--sev-baixa)", rank: 1 },
};

export const HEALTH: Record<HealthLevel, { label: string; color: string }> = {
  normal: { label: "Normal", color: "var(--status-ok)" },
  atencao: { label: "Atenção", color: "var(--status-maintenance)" },
  critico: { label: "Crítico", color: "var(--status-fault)" },
};

export const DUTY: Record<DutyStatus, { label: string; color: string; onDuty: boolean }> = {
  disponivel: { label: "Disponível", color: "var(--status-ok)", onDuty: true },
  em_patrulha: { label: "Em patrulha", color: "var(--agent-patrol)", onDuty: true },
  em_ocorrencia: { label: "Em ocorrência", color: "var(--status-fault)", onDuty: true },
  em_pausa: { label: "Em pausa", color: "var(--status-maintenance)", onDuty: true },
  fora_de_servico: { label: "Fora de serviço", color: "var(--status-disabled)", onDuty: false },
  afastado: { label: "Afastado", color: "var(--status-disabled)", onDuty: false },
};

export const ROLE: Record<AgentRole, { label: string; short: string; icon: LucideIcon }> = {
  agente_transito: { label: "Agente de trânsito", short: "Trânsito", icon: Hand },
  guarda_municipal: { label: "Guarda municipal", short: "GCM", icon: Shield },
  policial_militar: { label: "Policial militar", short: "PM", icon: Siren },
  outro: { label: "Outro", short: "Outro", icon: CircleHelp },
};

export const TYPE_ICON: Record<string, LucideIcon> = {
  radar: Radar,
  camera: Camera,
  balanca: Scale,
  veiculo_fiscalizacao_autonomo: Bot,
  cancela: Gauge,
  veiculo_transporte: BusFront,
  totem_estacionamento: Monitor,
  patinete: Bike,
  moto_agente: Zap,
  viatura: CarFront,
  semaforo: TrafficCone,
  outro: CircleHelp,
};

export const typeIcon = (code: string): LucideIcon => TYPE_ICON[code] ?? CircleHelp;

export const UNAVAILABLE_STATUSES: EquipmentStatus[] = [
  "mau_funcionamento",
  "em_manutencao",
  "furtado",
];

// Perfis de acesso: a descrição resume a matriz RBAC da API (app/core/permissions.py).
export const USER_ROLE: Record<UserRole, { label: string; description: string; icon: LucideIcon }> =
  {
    admin: {
      label: "Administrador",
      description: "Acesso total, inclusive a gestão de usuários.",
      icon: ShieldCheck,
    },
    gestor: {
      label: "Gestor",
      description: "Cadastra equipamentos, agentes e órgãos e define planos de manutenção.",
      icon: Briefcase,
    },
    operador: {
      label: "Operador",
      description: "Opera a Central: muda situações, reconhece alertas e despacha equipes.",
      icon: Headset,
    },
    consulta: {
      label: "Consulta",
      description: "Somente leitura da Central e do inventário.",
      icon: Eye,
    },
  };

export const USER_ROLE_ORDER: UserRole[] = ["admin", "gestor", "operador", "consulta"];

export const ORGANIZATION_KIND: Record<
  OrganizationKind,
  { label: string; hint: string; icon: LucideIcon }
> = {
  transito: {
    label: "Trânsito",
    hint: "Agentes de trânsito e equipamentos viários.",
    icon: TrafficCone,
  },
  guarda_municipal: { label: "Guarda municipal", hint: "Guardas municipais (GCM).", icon: Shield },
  policia_militar: { label: "Polícia militar", hint: "Policiais militares.", icon: Siren },
  concessionaria: {
    label: "Concessionária",
    hint: "Só equipamentos (empresas não têm agentes de campo).",
    icon: Building2,
  },
  outro: { label: "Outro", hint: "Outros órgãos parceiros.", icon: CircleHelp },
};
