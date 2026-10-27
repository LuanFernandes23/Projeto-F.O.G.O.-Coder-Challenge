import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FilePlus2, Pencil, Search, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Select } from "@/components/ui/controls";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/overlays";
import { Badge, Input, Label, Skeleton, Textarea } from "@/components/ui/primitives";
import { fieldErrors } from "@/features/inventory/form-errors";
import { api, ApiError, errorMessage } from "@/lib/api/client";
import type {
  ActionType,
  KnowledgeDocument,
  KnowledgeDocumentDetail,
  KnowledgeDocumentInput,
  KnowledgeHit,
  RiskClass,
  SituationKind,
} from "@/lib/api/types";
import { useAuth } from "@/lib/auth";

const DOC_TYPES: Record<string, string> = {
  procedimento: "Procedimento (POP)",
  plano_contingencia: "Plano de contingência",
  protocolo: "Protocolo",
  sla: "SLA",
  licao_aprendida: "Lição aprendida",
  politica: "Política",
};
const SITUATIONS: Record<SituationKind, string> = {
  precursor_falha: "Falha iminente",
  risco_equipamento: "Risco em 72 h",
  pico_regional: "Pico regional",
  deficit_efetivo: "Déficit de efetivo",
};
const ACTIONS: Record<ActionType, string> = {
  abrir_os_preventiva: "Abrir OS preventiva",
  alerta_preventivo: "Alerta preventivo",
  despachar_inspecao: "Despachar inspeção",
  reforcar_regiao: "Remanejar efetivo",
};
const RISK_LABEL: Record<string, string> = { baixo: "baixo", medio: "médio", alto: "alto" };
const RANK_LABEL: Record<string, string> = {
  bm25: "BM25",
  vetor_local: "vetor local",
  vetor_provedor: "vetor do provedor",
};

function asList<T extends string>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function KnowledgePanel() {
  const { can } = useAuth();
  const editable = can("knowledge:manage");
  const queryClient = useQueryClient();
  const documents = useQuery({
    queryKey: ["knowledge"],
    queryFn: () => api<KnowledgeDocument[]>("/knowledge/documents"),
  });
  const [query, setQuery] = useState("semáforo com temperatura alta e perda de sinal");
  const [situation, setSituation] = useState("");
  const [editing, setEditing] = useState<KnowledgeDocumentDetail | "novo" | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeDocument | null>(null);

  const search = useMutation({
    mutationFn: () =>
      api<KnowledgeHit[]>("/knowledge/search", {
        method: "POST",
        body: { query, situation: situation || null, limit: 5 },
        timeoutMs: 60_000,
      }),
    onError: (error) => toast.error(errorMessage(error)),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/knowledge/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
      setDeleting(null);
      toast.success("Documento excluído");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const openEditor = async (id: string) => {
    try {
      setEditing(await api<KnowledgeDocumentDetail>(`/knowledge/documents/${id}`));
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  return (
    <section aria-labelledby="kb-titulo" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="kb-titulo" className="font-semibold">
            Base de conhecimento
          </h2>
          <p className="text-sm text-muted-foreground">
            Procedimentos que o PROMETHEUS consulta (RAG híbrido: BM25 + vetores, fundidos por RRF).
            Os metadados dizem quais ações cada documento autoriza.
          </p>
        </div>
        {editable && (
          <Button onClick={() => setEditing("novo")}>
            <FilePlus2 /> Novo documento
          </Button>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          search.mutate();
        }}
        className="space-y-3 rounded-xl border bg-card p-4"
      >
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[16rem] flex-1 space-y-1.5">
            <Label htmlFor="kb-q">Testar busca</Label>
            <Input id="kb-q" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="w-48 space-y-1.5">
            <Label htmlFor="kb-sit">Situação</Label>
            <Select
              id="kb-sit"
              value={situation}
              onValueChange={setSituation}
              allowEmpty
              emptyLabel="Qualquer"
              placeholder="Qualquer"
              options={Object.entries(SITUATIONS).map(([value, label]) => ({ value, label }))}
            />
          </div>
          <Button type="submit" disabled={search.isPending || query.trim().length < 3}>
            <Search /> Buscar
          </Button>
        </div>
        {search.data && (
          <ol className="space-y-2">
            {search.data.map((hit, i) => (
              <li key={hit.chunk_id} className="rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold tabular-nums">{i + 1}.</span>
                  <span className="font-medium">{hit.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {hit.heading.split(" › ").slice(1).join(" › ")}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {hit.content.replaceAll("**", "")}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                  {Object.entries(hit.ranks).map(([name, rank]) => (
                    <Badge key={name} variant="outline">
                      {RANK_LABEL[name] ?? name} #{rank}
                    </Badge>
                  ))}
                  <Badge variant="secondary">RRF {hit.rrf.toFixed(4)}</Badge>
                  <Badge variant="secondary">similaridade {hit.similarity.toFixed(2)}</Badge>
                  <Badge variant="secondary">evidência {Math.round(hit.evidence * 100)}%</Badge>
                </div>
              </li>
            ))}
          </ol>
        )}
      </form>

      {documents.isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {(documents.data ?? []).map((d) => (
            <li key={d.id} className="flex flex-col gap-2 rounded-xl border bg-card p-3 text-sm">
              <div className="flex items-start gap-2">
                <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{d.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {DOC_TYPES[d.doc_type] ?? d.doc_type} · {d.chunks} trechos ·{" "}
                    {d.source === "arquivo" ? "arquivo" : "editado na tela"}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1 text-[11px]">
                {asList<SituationKind>(d.metadata.situacoes).map((s) => (
                  <Badge key={s} variant="outline">
                    {SITUATIONS[s] ?? s}
                  </Badge>
                ))}
                {asList<ActionType>(d.metadata.acoes_permitidas).map((a) => (
                  <Badge key={a}>{ACTIONS[a] ?? a}</Badge>
                ))}
                {typeof d.metadata.autonomia_max === "string" && (
                  <Badge variant="secondary">
                    autonomia até {RISK_LABEL[d.metadata.autonomia_max] ?? d.metadata.autonomia_max}
                  </Badge>
                )}
              </div>
              <div className="mt-auto flex gap-1 border-t pt-2">
                <Button size="xs" variant="ghost" onClick={() => setViewing(d.id)}>
                  Ver trechos
                </Button>
                {editable && (
                  <>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => void openEditor(d.id)}
                      aria-label={`Editar ${d.title}`}
                    >
                      <Pencil /> Editar
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      className="ml-auto text-destructive hover:text-destructive"
                      onClick={() => setDeleting(d)}
                      aria-label={`Excluir ${d.title}`}
                    >
                      <Trash2 />
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <DocumentViewer id={viewing} onClose={() => setViewing(null)} />
      <DocumentEditor document={editing} onClose={() => setEditing(null)} />

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Excluir “{deleting?.title}”?</DialogTitle>
            <DialogDescription>
              O PROMETHEUS deixa de consultar este documento.{" "}
              {deleting?.source === "arquivo" &&
                "Por ter vindo de um arquivo do repositório, ele volta quando o sistema reiniciar."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancelar
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => deleting && remove.mutate(deleting.id)}
            >
              Excluir documento
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function DocumentViewer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ["knowledge", id],
    queryFn: () => api<KnowledgeDocumentDetail>(`/knowledge/documents/${id}`),
    enabled: Boolean(id),
  });
  return (
    <Dialog open={Boolean(id)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{detail.data?.title ?? "Documento"}</DialogTitle>
          <DialogDescription>
            Trechos indexados (cada um tem lexemas para o BM25 e um vetor de 384 dimensões).
          </DialogDescription>
        </DialogHeader>
        <ol className="space-y-2">
          {detail.data?.chunk_list.map((c) => (
            <li key={c.id} className="rounded-lg border p-3 text-sm">
              <div className="text-xs font-medium text-muted-foreground">
                #{c.ordinal + 1} · {c.heading}
                {c.has_provider_embedding && " · + vetor do provedor"}
              </div>
              <p className="mt-1 whitespace-pre-line">{c.content.replaceAll("**", "")}</p>
            </li>
          ))}
        </ol>
      </DialogContent>
    </Dialog>
  );
}

interface GuardrailFinding {
  kind: string;
  label: string;
  excerpt: string;
}

const CHECKS: { kind: string[]; label: string }[] = [
  {
    kind: ["injecao_de_prompt"],
    label: "Sem instruções que tentem mudar as regras do agente (injeção de prompt)",
  },
  { kind: ["segredo"], label: "Sem chaves de API, tokens ou senhas" },
  { kind: ["dado_pessoal"], label: "Sem dados pessoais: CPF, telefone, e-mail (LGPD)" },
  { kind: ["tamanho", "estrutura"], label: "Até 20 mil caracteres, organizado em seções (##)" },
  {
    kind: ["autonomia"],
    label: "Autoriza no máximo ações de risco médio (risco alto só por revisão de código)",
  },
];

/** Verificações aplicadas antes de indexar: o que o PROMETHEUS lê precisa ser confiável. */
function GuardrailChecks({ blocked }: { blocked: GuardrailFinding[] }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3 text-xs" aria-live="polite">
      <p className="mb-1.5 flex items-center gap-1.5 font-medium">
        <ShieldCheck className="h-4 w-4 text-primary" aria-hidden /> Verificações de segurança ao
        salvar
      </p>
      <ul className="space-y-1">
        {CHECKS.map((check) => {
          const hits = blocked.filter((b) => check.kind.includes(b.kind));
          return (
            <li
              key={check.label}
              className={hits.length ? "text-destructive" : "text-muted-foreground"}
            >
              <span className="mr-1.5" aria-hidden>
                {hits.length ? "✕" : "•"}
              </span>
              {check.label}
              {hits.map((h) => (
                <span key={h.label + h.excerpt} className="block pl-4">
                  Encontrado: {h.label}
                  {h.excerpt && h.excerpt !== "…" ? ` — “${h.excerpt}”` : ""}
                </span>
              ))}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function stripFrontMatter(content: string): string {
  return content.replace(/^---\n[\s\S]*?\n---\n/, "").trim();
}

function DocumentEditor({
  document,
  onClose,
}: {
  document: KnowledgeDocumentDetail | "novo" | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("procedimento");
  const [situations, setSituations] = useState<SituationKind[]>([]);
  const [actions, setActions] = useState<ActionType[]>([]);
  const [defaultAction, setDefaultAction] = useState("");
  const [autonomy, setAutonomy] = useState<RiskClass>("baixo");
  const [body, setBody] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [blocked, setBlocked] = useState<GuardrailFinding[]>([]);
  const existing = document && document !== "novo" ? document : null;

  useEffect(() => {
    if (!document) return;
    setErrors({});
    setBlocked([]);
    if (document === "novo") {
      setTitle("");
      setDocType("procedimento");
      setSituations([]);
      setActions([]);
      setDefaultAction("");
      setAutonomy("baixo");
      setBody("## Quando aplicar\n\n## Ação\n");
      return;
    }
    setTitle(document.title);
    setDocType(document.doc_type);
    setSituations(asList<SituationKind>(document.metadata.situacoes));
    setActions(asList<ActionType>(document.metadata.acoes_permitidas));
    setDefaultAction(
      typeof document.metadata.acao_padrao === "string" ? document.metadata.acao_padrao : "",
    );
    setAutonomy((document.metadata.autonomia_max as RiskClass) ?? "baixo");
    setBody(stripFrontMatter(document.content));
  }, [document]);

  const save = useMutation({
    mutationFn: (payload: KnowledgeDocumentInput) =>
      api<KnowledgeDocumentDetail>("/knowledge/documents", {
        method: "POST",
        body: payload,
        timeoutMs: 120_000,
      }),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
      toast.success("Documento salvo e reindexado", {
        description: `${saved.chunk_list.length} trechos`,
      });
      onClose();
    },
    onError: (error) => {
      setErrors(fieldErrors(error));
      const found = error instanceof ApiError ? error.problem.guardrails : undefined;
      setBlocked(Array.isArray(found) ? (found as GuardrailFinding[]) : []);
      toast.error(errorMessage(error));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate({
      slug: existing?.slug ?? null,
      title,
      doc_type: docType,
      situations,
      allowed_actions: actions,
      default_action: (defaultAction || null) as ActionType | null,
      max_autonomy: autonomy,
      equipment_types: asList<string>(existing?.metadata.tipos_equipamento),
      regions: asList<string>(existing?.metadata.regioes),
      body,
    });
  };

  const toggle = <T,>(list: T[], value: T) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  return (
    <Dialog open={Boolean(document)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl">
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <DialogHeader>
            <DialogTitle>{existing ? `Editar ${existing.title}` : "Novo documento"}</DialogTitle>
            <DialogDescription>
              Markdown com títulos (##): cada seção vira um trecho pesquisável.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
            <div className="space-y-1.5">
              <Label htmlFor="kb-title">Título</Label>
              <Input
                id="kb-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-invalid={Boolean(errors.title)}
              />
              {errors.title && <p className="text-xs text-destructive">{errors.title}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="kb-type">Tipo</Label>
              <Select
                id="kb-type"
                value={docType}
                onValueChange={setDocType}
                options={Object.entries(DOC_TYPES).map(([value, label]) => ({ value, label }))}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <span className="text-sm font-medium">Situações em que se aplica</span>
            <div className="flex flex-wrap gap-1.5">
              {(Object.keys(SITUATIONS) as SituationKind[]).map((s) => (
                <Chip
                  key={s}
                  pressed={situations.includes(s)}
                  onToggle={() => setSituations(toggle(situations, s))}
                >
                  {SITUATIONS[s]}
                </Chip>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_12rem_10rem]">
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Ações que autoriza</span>
              <div className="flex flex-wrap gap-1.5">
                {(Object.keys(ACTIONS) as ActionType[]).map((a) => (
                  <Chip
                    key={a}
                    pressed={actions.includes(a)}
                    onToggle={() => setActions(toggle(actions, a))}
                  >
                    {ACTIONS[a]}
                  </Chip>
                ))}
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="kb-default">Ação padrão</Label>
              <Select
                id="kb-default"
                value={defaultAction}
                onValueChange={setDefaultAction}
                allowEmpty
                emptyLabel="Nenhuma"
                placeholder="Nenhuma"
                options={actions.map((a) => ({ value: a, label: ACTIONS[a] }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="kb-autonomy">Autonomia máxima</Label>
              <Select
                id="kb-autonomy"
                value={autonomy}
                onValueChange={(v) => setAutonomy(v as RiskClass)}
                options={[
                  { value: "baixo", label: "Risco baixo" },
                  { value: "medio", label: "Risco médio" },
                ]}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="kb-body">Conteúdo (markdown)</Label>
            <Textarea
              id="kb-body"
              rows={12}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className="font-mono text-xs"
              aria-invalid={Boolean(errors.body)}
            />
            {errors.body && !blocked.length && (
              <p className="text-xs text-destructive">{errors.body}</p>
            )}
          </div>
          <GuardrailChecks blocked={blocked} />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Indexando…" : "Salvar e indexar"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
