import { fetchEventSource } from "@microsoft/fetch-event-source";
import { Flame, Loader2, SendHorizontal, ShieldCheck, Square, Wrench } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/overlays";
import { Textarea } from "@/components/ui/primitives";
import { tokenStore } from "@/lib/auth-store";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

interface Message {
  role: "user" | "assistant";
  content: string;
  tools?: string[];
  notices?: string[];
  error?: boolean;
}

const SUGGESTIONS = [
  "Onde reforçar o efetivo hoje à noite?",
  "Quais equipamentos devo antecipar a preventiva?",
  "Há algo fora do padrão na cidade agora?",
  "O que diz o procedimento para semáforo com sinais de falha?",
];

const TOOL_LABEL: Record<string, string> = {
  buscar_conhecimento: "base de conhecimento",
  risco_previsto: "previsão de risco",
  equipamentos_em_risco: "equipamentos em risco",
  reforco_de_efetivo: "efetivo recomendado",
  anomalias_agora: "anomalias",
  qualidade_do_modelo: "qualidade do modelo",
  decisoes_recentes: "decisões",
  pedidos_pendentes: "pedidos pendentes",
};

/** Negrito (**x**) e listas simples ("- "): o suficiente para as respostas do agente. */
function renderText(text: string): ReactNode {
  const lines = text.split("\n");
  const bold = (line: string) =>
    line
      .split(/(\*\*[^*]+\*\*)/g)
      .map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i}>{part.slice(2, -2)}</strong>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      );
  return lines.map((line, i) => {
    const item = /^\s*[-*•]\s+(.*)$/.exec(line);
    if (item) {
      return (
        <div key={i} className="flex gap-1.5 pl-1">
          <span aria-hidden>•</span>
          <span>{bold(item[1] ?? "")}</span>
        </div>
      );
    }
    return line.trim() ? <p key={i}>{bold(line)}</p> : <div key={i} className="h-1.5" />;
  });
}

const PROTECTIONS = [
  "Só consulta: não executa ações",
  "Dados pessoais e segredos são removidos antes de ir ao modelo",
  "Recusa instruções que tentem mudar as regras",
  "Só assuntos da operação da cidade",
  "Responde com fontes (previsões, base, decisões)",
];

function Protections() {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b bg-muted/30 px-4 py-2 text-xs">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 font-medium"
      >
        <ShieldCheck className="h-3.5 w-3.5 text-primary" aria-hidden /> Proteções ativas
        <span className="ml-auto text-muted-foreground">{open ? "ocultar" : "ver"}</span>
      </button>
      {open && (
        <ul className="mt-1.5 space-y-0.5 pl-5 text-muted-foreground">
          {PROTECTIONS.map((item) => (
            <li key={item} className="list-disc">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PrometheusChat({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { can } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Bloco explícito: em navegadores recentes scrollIntoView devolve uma Promise, e o React
    // trataria o retorno como função de limpeza.
    void bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);
  useEffect(() => () => controller.current?.abort(), []);

  const update = (fn: (last: Message) => Message) =>
    setMessages((current) => [...current.slice(0, -1), fn(current[current.length - 1]!)]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    const history: Message[] = [
      ...messages.filter((m) => !m.error),
      { role: "user", content: question },
    ];
    setMessages([...history, { role: "assistant", content: "", tools: [] }]);
    setDraft("");
    setBusy(true);
    controller.current = new AbortController();
    try {
      await fetchEventSource("/api/v1/prometheus/chat", {
        method: "POST",
        signal: controller.current.signal,
        headers: {
          Authorization: `Bearer ${tokenStore.get() ?? ""}`,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })) }),
        openWhenHidden: true,
        onmessage(event) {
          const data = JSON.parse(event.data) as {
            text?: string;
            name?: string;
            message?: string;
            notices?: string[];
          };
          if (event.event === "guardrail" && data.notices) {
            update((last) => ({ ...last, notices: [...(last.notices ?? []), ...data.notices!] }));
          } else if (event.event === "token" && data.text) {
            update((last) => ({ ...last, content: last.content + data.text }));
          } else if (event.event === "tool" && data.name) {
            update((last) => ({
              ...last,
              tools: [...new Set([...(last.tools ?? []), data.name!])],
            }));
          } else if (event.event === "error") {
            update((last) => ({
              ...last,
              content: data.message ?? "Erro no modelo de IA.",
              error: true,
            }));
          }
        },
        onerror(error) {
          throw error; // sem reconexão automática: uma pergunta = uma resposta
        },
      });
    } catch {
      if (!controller.current?.signal.aborted) {
        update((last) => ({
          ...last,
          content: last.content || "Não foi possível falar com o PROMETHEUS.",
          error: !last.content,
        }));
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send(draft);
  };

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={
        <span className="flex items-center gap-2">
          <Flame className="h-4 w-4 text-[hsl(var(--brand-fire))]" aria-hidden /> Pergunte ao
          PROMETHEUS
        </span>
      }
      description="Responde com as previsões, a base de conhecimento e as decisões registradas. Só consulta: não executa ações."
      className="max-w-lg"
    >
      <div className="flex h-full flex-col">
        <Protections />
        <div className="fogo-scroll flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
          {messages.length === 0 && (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Sugestões:</p>
              <ul className="space-y-1.5">
                {SUGGESTIONS.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      onClick={() => void send(s)}
                      className="w-full rounded-lg border px-3 py-2 text-left text-sm hover:border-primary/50 hover:bg-accent"
                    >
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={cn(
                "max-w-[92%] space-y-1 rounded-xl px-3 py-2 text-sm",
                m.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted",
                m.error && "border border-destructive/40 bg-destructive/10",
              )}
            >
              {m.notices?.map((notice) => (
                <p
                  key={notice}
                  className="flex items-start gap-1 text-[11px] text-muted-foreground"
                >
                  <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-primary" aria-hidden />{" "}
                  {notice}
                </p>
              ))}
              {m.tools && m.tools.length > 0 && (
                <p className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                  <Wrench className="h-3 w-3" aria-hidden /> Consultou:{" "}
                  {m.tools.map((t) => TOOL_LABEL[t] ?? t).join(", ")}
                </p>
              )}
              {m.content ? (
                <div className="space-y-1 leading-relaxed">{renderText(m.content)}</div>
              ) : (
                <Loader2
                  className="h-4 w-4 animate-spin text-muted-foreground"
                  aria-label="Pensando"
                />
              )}
              {m.error && can("ai:configure") && (
                <Link
                  to="/administracao/ia"
                  onClick={() => onOpenChange(false)}
                  className="text-xs text-primary underline"
                >
                  Configurar modelo de IA
                </Link>
              )}
            </div>
          ))}
          <div ref={bottom} />
        </div>
        <form onSubmit={submit} className="flex items-end gap-2 border-t p-3">
          <Textarea
            rows={2}
            value={draft}
            aria-label="Pergunta"
            placeholder="Pergunte sobre riscos, equipamentos, efetivo ou procedimentos"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send(draft);
              }
            }}
            className="min-h-0 flex-1 resize-none"
          />
          {busy ? (
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Parar"
              onClick={() => controller.current?.abort()}
            >
              <Square />
            </Button>
          ) : (
            <Button type="submit" size="icon" aria-label="Enviar" disabled={!draft.trim()}>
              <SendHorizontal />
            </Button>
          )}
        </form>
      </div>
    </Sheet>
  );
}
