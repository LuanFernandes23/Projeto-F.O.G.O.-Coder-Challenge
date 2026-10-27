import { BookOpen, BrainCircuit, Building2, Gauge, UserCog } from "lucide-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";
import { useAuth } from "@/lib/auth";

import { AiSettingsPanel } from "./AiSettingsPanel";
import { AutonomyPanel } from "./AutonomyPanel";
import { KnowledgePanel } from "./KnowledgePanel";
import { OrganizationsPanel } from "./OrganizationsPanel";
import { UsersPanel } from "./UsersPanel";

const SECTIONS = [
  { id: "usuarios", label: "Usuários", icon: UserCog, permission: "user:manage" },
  { id: "orgaos", label: "Órgãos", icon: Building2, permission: "organization:write" },
  { id: "ia", label: "Inteligência artificial", icon: BrainCircuit, permission: "ai:configure" },
  { id: "autonomia", label: "Autonomia", icon: Gauge, permission: "prometheus:manage" },
  {
    id: "conhecimento",
    label: "Base de conhecimento",
    icon: BookOpen,
    permission: "knowledge:manage",
  },
] as const;

/** Cadastros administrativos; cada aba aparece só para quem tem a permissão (a API confere de novo). */
export function AdminPage() {
  const { section } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const allowed = SECTIONS.filter((s) => can(s.permission));
  const first = allowed[0];

  if (!first)
    return (
      <p className="p-6 text-sm text-muted-foreground">
        Seu perfil não tem acesso à administração.
      </p>
    );
  if (!allowed.some((s) => s.id === section))
    return <Navigate to={`/administracao/${first.id}`} replace />;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <div>
        <h1 className="text-lg font-semibold">Administração</h1>
        <p className="text-sm text-muted-foreground">
          Usuários, órgãos, o modelo de IA e as regras do PROMETHEUS.
        </p>
      </div>
      <Tabs value={section} onValueChange={(value) => navigate(`/administracao/${value}`)}>
        {allowed.length > 1 && (
          <TabsList className="fogo-scroll mb-4 h-10 max-w-full overflow-x-auto">
            {allowed.map(({ id, label, icon: Icon }) => (
              <TabsTrigger key={id} value={id} className="px-4 py-1.5 text-sm">
                <Icon className="h-4 w-4" aria-hidden /> {label}
              </TabsTrigger>
            ))}
          </TabsList>
        )}
        <TabsContent value="usuarios">
          <UsersPanel />
        </TabsContent>
        <TabsContent value="orgaos">
          <OrganizationsPanel />
        </TabsContent>
        <TabsContent value="ia">
          <AiSettingsPanel />
        </TabsContent>
        <TabsContent value="autonomia">
          <AutonomyPanel />
        </TabsContent>
        <TabsContent value="conhecimento">
          <KnowledgePanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
