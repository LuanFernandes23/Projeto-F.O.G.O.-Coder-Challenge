import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Sigma, UserCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChoiceCards } from "@/components/ui/choice-cards";
import { Switch } from "@/components/ui/controls";
import { Badge, Input, Label, Skeleton } from "@/components/ui/primitives";
import { RISK_LABEL } from "@/features/prometheus/DecisionCard";
import { api, errorMessage } from "@/lib/api/client";
import type { Policy, PrometheusMode, PrometheusSettings } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";

const MODES: { value: PrometheusMode; label: string; description: string; icon: typeof Play }[] = [
  {
    value: "autonomo",
    label: "Autônomo",
    description: "Executa sozinho o que passar na política; o resto pede aprovação.",
    icon: Play,
  },
  {
    value: "sugestao",
    label: "Só sugestão",
    description: "Toda ação vira pedido de aprovação humana.",
    icon: UserCheck,
  },
  { value: "pausado", label: "Pausado", description: "Não abre novas decisões.", icon: Pause },
];

/** Governança do PROMETHEUS: modo de operação e limiar por tipo de ação. */
export function AutonomyPanel() {
  const { can } = useAuth();
  const editable = can("prometheus:manage");
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["prometheus", "settings"],
    queryFn: () => api<PrometheusSettings>("/prometheus/settings"),
  });
  const [mode, setMode] = useState<PrometheusMode>("autonomo");
  const [ttl, setTtl] = useState(30);
  const [policies, setPolicies] = useState<Policy[]>([]);

  useEffect(() => {
    if (!settings.data) return;
    setMode(settings.data.mode);
    setTtl(settings.data.approval_ttl_minutes);
    setPolicies(settings.data.policies);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api<PrometheusSettings>("/prometheus/settings", {
        method: "PUT",
        body: {
          mode,
          approval_ttl_minutes: ttl,
          policies: policies.map(({ action_type, threshold, enabled, max_per_hour }) => ({
            action_type,
            threshold,
            enabled,
            max_per_hour,
          })),
        },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["prometheus", "settings"], data);
      void queryClient.invalidateQueries({ queryKey: ["prometheus", "stats"] });
      toast.success("Política de autonomia salva");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const patch = (action: string, changes: Partial<Policy>) =>
    setPolicies((current) =>
      current.map((p) => (p.action_type === action ? { ...p, ...changes } : p)),
    );

  if (settings.isLoading) return <Skeleton className="h-80" />;

  return (
    <section aria-labelledby="autonomia-titulo" className="space-y-4">
      <div>
        <h2 id="autonomia-titulo" className="font-semibold">
          Autonomia do PROMETHEUS
        </h2>
        <p className="text-sm text-muted-foreground">
          Quando o agente pode agir sozinho e quando precisa de um humano. A decisão é do sistema,
          nunca do modelo de IA.
        </p>
      </div>

      <div className="flex items-start gap-3 rounded-xl border bg-card p-4 text-sm">
        <Sigma className="mt-0.5 h-5 w-5 shrink-0 text-primary" aria-hidden />
        <div className="space-y-1">
          <p>
            <strong>score = confiança × evidência.</strong> A confiança é a probabilidade medida da
            previsão (calibrada no backtest ou pela taxa de acerto das detecções ao vivo); a
            evidência é a aderência do procedimento da base de conhecimento que autoriza a ação.
          </p>
          <p className="text-muted-foreground">
            Age sozinho só se: o modo for autônomo, o score atingir o limiar da ação, o procedimento
            permitir o nível de risco e o teto por hora não tiver sido atingido. Ações de risco alto
            sempre pedem aprovação.
          </p>
        </div>
      </div>

      <fieldset className="space-y-2" disabled={!editable}>
        <legend className="mb-1.5 text-sm font-medium">Modo de operação</legend>
        <ChoiceCards
          label="Modo de operação"
          value={mode}
          onChange={setMode}
          choices={MODES}
          className="sm:grid-cols-3"
        />
      </fieldset>

      <div className="overflow-hidden rounded-xl border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Ação</th>
              <th className="px-3 py-2 text-left font-medium">Automática</th>
              <th className="px-3 py-2 text-left font-medium">Limiar do score</th>
              <th className="px-3 py-2 text-left font-medium">Máx. por hora</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {policies.map((p) => {
              const high = p.risk_class === "alto";
              return (
                <tr key={p.action_type}>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{p.action_label}</div>
                    <Badge variant="secondary">{RISK_LABEL[p.risk_class]}</Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    {high ? (
                      <span className="text-xs text-muted-foreground">Sempre pede aprovação</span>
                    ) : (
                      <Switch
                        checked={p.enabled}
                        disabled={!editable}
                        onCheckedChange={(enabled) => patch(p.action_type, { enabled })}
                        aria-label={`Execução automática: ${p.action_label}`}
                      />
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={p.threshold}
                        disabled={!editable || high}
                        onChange={(e) =>
                          patch(p.action_type, { threshold: Number(e.target.value) })
                        }
                        className="w-32 accent-[hsl(var(--primary))]"
                        aria-label={`Limiar: ${p.action_label}`}
                      />
                      <span className="w-10 tabular-nums">{Math.round(p.threshold * 100)}%</span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Input
                      type="number"
                      min={0}
                      max={100}
                      value={p.max_per_hour}
                      disabled={!editable || high}
                      onChange={(e) =>
                        patch(p.action_type, { max_per_hour: Number(e.target.value) })
                      }
                      className="h-8 w-20"
                      aria-label={`Máximo por hora: ${p.action_label}`}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="ttl">Pedido de aprovação expira em (min)</Label>
          <Input
            id="ttl"
            type="number"
            min={5}
            max={1440}
            value={ttl}
            disabled={!editable}
            onChange={(e) => setTtl(Number(e.target.value))}
            className="w-28"
          />
        </div>
        {editable && (
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            Salvar política
          </Button>
        )}
      </div>
    </section>
  );
}
