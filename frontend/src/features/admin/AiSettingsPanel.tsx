import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  KeyRound,
  ListRestart,
  Lock,
  Plug,
  Server,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ChoiceCards } from "@/components/ui/choice-cards";
import { Select, Switch } from "@/components/ui/controls";
import {
  Input,
  Label,
  Skeleton,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "@/components/ui/primitives";
import { fieldErrors } from "@/features/inventory/form-errors";
import { api, errorMessage } from "@/lib/api/client";
import type {
  AiProvider,
  AiSave,
  AiSettings,
  AiSettingsInput,
  AiTest,
  AiUsage,
} from "@/lib/api/types";

const PROVIDER_HINT: Record<AiProvider, string> = {
  openai: "GPT-4.1, GPT-4o… Também oferece embeddings.",
  anthropic: "Claude (Haiku, Sonnet). Sem embeddings: usa o modelo local.",
  gemini: "Gemini 2.5 Flash/Pro. Também oferece embeddings.",
  openai_compatible: "Ollama local, OpenRouter, Azure, Groq… (URL base).",
};
const PROVIDER_ICON = {
  openai: Plug,
  anthropic: Plug,
  gemini: Plug,
  openai_compatible: Server,
} as const;
const USAGE_LABEL: Record<string, string> = {
  chat: "Chat",
  prometheus_plano: "Plano do PROMETHEUS",
  embeddings_base: "Indexação da base",
  embeddings_busca: "Busca na base",
  teste_conexao: "Teste de conexão",
};

export function AiSettingsPanel() {
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["ai-settings"],
    queryFn: () => api<AiSettings>("/ai/settings"),
  });
  const usage = useQuery({
    queryKey: ["ai-usage"],
    queryFn: () => api<AiUsage[]>("/ai/usage", { query: { days: 14 } }),
  });

  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState<AiProvider>("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [embeddings, setEmbeddings] = useState<"local" | "openai" | "gemini">("local");
  const [calls, setCalls] = useState(200);
  const [tokens, setTokens] = useState(200_000);
  const [models, setModels] = useState<string[]>([]);
  const [test, setTest] = useState<AiTest | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setEnabled(s.enabled);
    setProvider(s.provider);
    setModel(s.model);
    setBaseUrl(s.base_url ?? "");
    setEmbeddings(s.embeddings_provider);
    setCalls(s.daily_call_limit);
    setTokens(s.daily_token_limit);
  }, [settings.data]);

  const current = settings.data;
  const option = current?.providers.find((p) => p.code === provider);
  const candidate = () => ({
    provider,
    model,
    base_url: baseUrl || null,
    api_key: apiKey || null,
  });

  const save = useMutation({
    mutationFn: (body: AiSettingsInput) =>
      api<AiSave>("/ai/settings", { method: "PUT", body, timeoutMs: 120_000 }),
    onSuccess: (result) => {
      queryClient.setQueryData(["ai-settings"], result.settings);
      setApiKey("");
      setErrors({});
      toast.success("Configuração de IA salva", {
        description:
          result.reindexed_chunks !== null && result.reindexed_chunks !== undefined
            ? `${result.reindexed_chunks} trechos da base reindexados.`
            : result.settings.usable
              ? "O PROMETHEUS e o chat já usam este modelo."
              : "IA desligada: o sistema segue no modo determinístico.",
      });
    },
    onError: (error) => {
      setErrors(fieldErrors(error));
      toast.error(errorMessage(error));
    },
  });

  const runTest = useMutation({
    mutationFn: () =>
      api<AiTest>("/ai/settings/test", { method: "POST", body: candidate(), timeoutMs: 60_000 }),
    onSuccess: setTest,
    onError: (error) => toast.error(errorMessage(error)),
  });

  const listModels = useMutation({
    mutationFn: () =>
      api<string[]>("/ai/models", { method: "POST", body: candidate(), timeoutMs: 30_000 }),
    onSuccess: (list) => {
      setModels(list);
      toast.success(`${list.length} modelos disponíveis`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const submit = (event: FormEvent, clearKey = false) => {
    event.preventDefault();
    save.mutate({
      enabled,
      provider,
      model,
      base_url: baseUrl || null,
      api_key: apiKey || null,
      clear_key: clearKey,
      embeddings_provider: embeddings,
      daily_call_limit: calls,
      daily_token_limit: tokens,
    });
  };

  if (settings.isLoading || !current) return <Skeleton className="h-96" />;
  const sameProviderKey = current.provider === provider && current.has_key;

  return (
    <section aria-labelledby="ia-titulo" className="grid gap-4 lg:grid-cols-[1fr_20rem]">
      <form onSubmit={submit} className="space-y-5 rounded-xl border bg-card p-4" noValidate>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="ia-titulo" className="font-semibold">
              Modelo de IA
            </h2>
            <p className="text-sm text-muted-foreground">
              Use a sua própria chave. Sem chave, o PROMETHEUS decide por regras e a busca na base
              usa o modelo local.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Usar modelo de IA" />
            {enabled ? "Ligado" : "Desligado"}
          </label>
        </div>

        <fieldset className="space-y-1.5">
          <legend className="mb-1.5 text-sm font-medium">Provedor</legend>
          <ChoiceCards
            label="Provedor"
            value={provider}
            onChange={(p) => {
              setProvider(p);
              setModels([]);
              setTest(null);
              const next = current.providers.find((o) => o.code === p);
              if (next && p !== current.provider) setModel(next.default_model);
              if (p !== "openai" && p !== "gemini") setEmbeddings("local");
            }}
            choices={current.providers.map((p) => ({
              value: p.code,
              label: p.label,
              description: PROVIDER_HINT[p.code],
              icon: PROVIDER_ICON[p.code],
            }))}
          />
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ai-model">Modelo</Label>
            <div className="flex gap-2">
              {models.length ? (
                <Select
                  id="ai-model"
                  value={model}
                  onValueChange={setModel}
                  options={models.map((m) => ({ value: m, label: m }))}
                />
              ) : (
                <Input
                  id="ai-model"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder={option?.default_model}
                />
              )}
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label="Listar modelos da chave"
                title="Listar modelos disponíveis (sem custo)"
                disabled={listModels.isPending}
                onClick={() => listModels.mutate()}
              >
                <ListRestart />
              </Button>
            </div>
          </div>
          {option?.needs_base_url && (
            <div className="space-y-1.5">
              <Label htmlFor="ai-base">URL base</Label>
              <Input
                id="ai-base"
                value={baseUrl}
                placeholder="http://host.docker.internal:11434/v1"
                onChange={(e) => setBaseUrl(e.target.value)}
                aria-invalid={Boolean(errors.base_url)}
              />
              {errors.base_url && <p className="text-xs text-destructive">{errors.base_url}</p>}
            </div>
          )}
          <div className="space-y-1.5 sm:col-span-2">
            <Label htmlFor="ai-key">Chave de API</Label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <KeyRound
                  className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  id="ai-key"
                  type="password"
                  autoComplete="off"
                  className="pl-8"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={
                    sameProviderKey
                      ? `Chave salva ${current.key_hint ?? ""} (deixe em branco para manter)`
                      : "Cole a chave do provedor"
                  }
                />
              </div>
              {sameProviderKey && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={(e) => submit(e, true)}
                  title="Remover a chave salva"
                >
                  <Trash2 /> Remover
                </Button>
              )}
            </div>
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Lock className="h-3 w-3" aria-hidden /> Cifrada no servidor; só os 4 últimos
              caracteres voltam para a tela.
            </p>
          </div>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Embeddings da base de conhecimento</legend>
          <div className="flex flex-wrap gap-2 text-sm">
            {(
              [
                "local",
                provider === "openai" ? "openai" : provider === "gemini" ? "gemini" : null,
              ] as const
            )
              .filter((v): v is "local" | "openai" | "gemini" => v !== null)
              .map((value) => (
                <label key={value} className="flex items-center gap-2 rounded-lg border px-3 py-2">
                  <input
                    type="radio"
                    name="embeddings"
                    checked={embeddings === value}
                    onChange={() => setEmbeddings(value)}
                  />
                  {value === "local"
                    ? "Modelo local (padrão, sem custo)"
                    : `Local + ${option?.label} (busca híbrida com 3 rankings)`}
                </label>
              ))}
          </div>
          {errors.embeddings_provider && (
            <p className="text-xs text-destructive">{errors.embeddings_provider}</p>
          )}
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ai-calls">Limite diário de chamadas</Label>
            <Input
              id="ai-calls"
              type="number"
              min={1}
              value={calls}
              onChange={(e) => setCalls(Number(e.target.value))}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ai-tokens">Limite diário de tokens</Label>
            <Input
              id="ai-tokens"
              type="number"
              min={1000}
              step={1000}
              value={tokens}
              onChange={(e) => setTokens(Number(e.target.value))}
            />
          </div>
        </div>

        {test && (
          <div
            role="status"
            className={`flex items-start gap-2 rounded-lg border p-3 text-sm ${test.ok ? "border-[hsl(var(--status-ok)/0.4)]" : "border-destructive/40"}`}
          >
            {test.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 text-status-ok" aria-hidden />
            ) : (
              <XCircle className="mt-0.5 h-4 w-4 text-destructive" aria-hidden />
            )}
            <div>
              <div className="font-medium">{test.ok ? "Conexão funcionando" : "Falhou"}</div>
              <div className="text-xs text-muted-foreground">
                {test.ok
                  ? `Resposta "${test.reply}" em ${test.latency_ms} ms · ${test.input_tokens + test.output_tokens} tokens`
                  : test.error}
              </div>
            </div>
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          <Button
            type="button"
            variant="outline"
            disabled={runTest.isPending}
            onClick={() => runTest.mutate()}
          >
            <Plug /> {runTest.isPending ? "Testando…" : "Testar conexão"}
          </Button>
          <Button type="submit" disabled={save.isPending}>
            Salvar
          </Button>
        </div>
      </form>

      <aside className="space-y-3">
        <div className="space-y-2 rounded-xl border bg-card p-4 text-sm">
          <h3 className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-primary" aria-hidden /> Situação
          </h3>
          <p className="text-muted-foreground">
            {current.usable
              ? `Ativo: ${current.providers.find((p) => p.code === current.provider)?.label} · ${current.model}`
              : "Modo determinístico (sem IA): previsões, busca e decisões funcionam normalmente."}
          </p>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            <li>Com IA: o PROMETHEUS escolhe a ação e escreve a justificativa citando a base.</li>
            <li>O chat “Pergunte ao PROMETHEUS” exige IA.</li>
            <li>A decisão de agir sozinho nunca é da IA: é da política de autonomia.</li>
          </ul>
        </div>
        <div className="space-y-2 rounded-xl border bg-card p-4">
          <h3 className="text-sm font-medium">Consumo (14 dias)</h3>
          {usage.data && usage.data.length ? (
            <Table>
              <THead>
                <TR>
                  <TH className="px-2">Dia</TH>
                  <TH className="px-2">Uso</TH>
                  <TH className="px-2 text-right">Tokens</TH>
                  <TH className="px-2 text-right">US$</TH>
                </TR>
              </THead>
              <TBody>
                {usage.data.slice(0, 10).map((u) => (
                  <TR key={u.day + u.feature}>
                    <TD className="px-2 tabular-nums">
                      {u.day.slice(8, 10)}/{u.day.slice(5, 7)}
                    </TD>
                    <TD className="px-2 text-xs">
                      {USAGE_LABEL[u.feature] ?? u.feature.replaceAll("_", " ")}
                      {u.errors ? ` (${u.errors} erro)` : ""}
                    </TD>
                    <TD className="px-2 text-right tabular-nums">
                      {(u.input_tokens + u.output_tokens).toLocaleString("pt-BR")}
                    </TD>
                    <TD className="px-2 text-right tabular-nums">
                      {u.cost_usd.toLocaleString("pt-BR", {
                        minimumFractionDigits: 4,
                        maximumFractionDigits: 4,
                      })}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          ) : (
            <p className="text-xs text-muted-foreground">Nenhum uso registrado.</p>
          )}
        </div>
      </aside>
    </section>
  );
}
