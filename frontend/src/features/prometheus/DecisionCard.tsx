import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  Clock,
  Cpu,
  Sparkles,
  UserCheck,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge, Textarea } from "@/components/ui/primitives";
import { ToneCard, type Tone } from "@/components/ui/tone";
import type { Decision, DecisionStatus, RiskClass } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { fromNow } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useAnswerDecision } from "@/features/prediction/api";

const STATUS: Record<DecisionStatus, { label: string; tone: Tone; icon: LucideIcon }> = {
  pendente: { label: "Aguardando aprovação", tone: "warn", icon: Clock },
  executada: { label: "Executada", tone: "ok", icon: Check },
  rejeitada: { label: "Rejeitada", tone: "neutral", icon: X },
  expirada: { label: "Expirada sem resposta", tone: "neutral", icon: Clock },
  falhou: { label: "Sem ação", tone: "bad", icon: AlertTriangle },
};

export const RISK_LABEL: Record<RiskClass, string> = {
  baixo: "Risco baixo",
  medio: "Risco médio",
  alto: "Risco alto",
};

interface Citation {
  n: number;
  title: string;
  heading: string;
  content: string;
  similarity: number;
  applies?: boolean;
}

/** Primeiro os trechos que valem para a situação; decisões antigas não têm `applies`. */
function shownCitations(citations: Decision["citations"]): Citation[] {
  const all = citations as unknown as Citation[];
  const applicable = all.filter((c) => c.applies !== false);
  return (applicable.length > 0 ? applicable : all).slice(0, 3);
}

interface Score {
  confidence?: number;
  evidence?: number;
  score?: number;
  threshold?: number;
  reasons?: string[];
}

function ScoreBar({ score }: { score: Score }) {
  const value = Math.round((score.score ?? 0) * 100);
  const threshold = Math.round((score.threshold ?? 0) * 100);
  return (
    <div className="space-y-1">
      <div className="relative h-1.5 rounded-full bg-muted" aria-hidden>
        <div
          className={cn(
            "absolute inset-y-0 left-0 rounded-full",
            value >= threshold ? "bg-status-ok" : "bg-status-maintenance",
          )}
          style={{ width: `${value}%` }}
        />
        <div
          className="absolute -top-1 h-3.5 w-0.5 bg-foreground/70"
          style={{ left: `${threshold}%` }}
        />
      </div>
      <p className="text-[11px] tabular-nums text-muted-foreground">
        Score {value}% = confiança {Math.round((score.confidence ?? 0) * 100)}% × evidência{" "}
        {Math.round((score.evidence ?? 0) * 100)}% · limiar {threshold}%
      </p>
    </div>
  );
}

/** Uma decisão do PROMETHEUS: o que viu, o que propôs, por quê, e (se pendente) aprovar/rejeitar. */
export function DecisionCard({
  decision,
  defaultOpen = false,
}: {
  decision: Decision;
  defaultOpen?: boolean;
}) {
  const { can } = useAuth();
  const answer = useAnswerDecision();
  const [open, setOpen] = useState(defaultOpen);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const status = STATUS[decision.status];
  const pending = decision.status === "pendente";
  const score = decision.score as Score;
  const auto = decision.mode === "automatica";
  const StatusIcon = decision.status === "executada" ? (auto ? Zap : UserCheck) : status.icon;
  const result = decision.result as { message?: string } | null;

  return (
    <ToneCard as="article" tone={status.tone} glow={pending} className="space-y-2 p-3 text-sm">
      <header className="flex items-start gap-2">
        <StatusIcon className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--tone))]" aria-hidden />
        <div className="min-w-0 flex-1">
          <h3 className="font-medium leading-snug">{decision.title}</h3>
          <p className="text-xs text-muted-foreground">
            {decision.status === "executada"
              ? auto
                ? "Executada sozinho"
                : "Aprovada e executada"
              : status.label}
            {" · "}
            {fromNow(decision.decided_at ?? decision.created_at)}
          </p>
        </div>
        <Badge
          variant="outline"
          className="shrink-0 gap-1"
          title={
            decision.planner === "llm"
              ? "Planejado pelo modelo de IA"
              : "Planejado por regras (sem IA)"
          }
        >
          {decision.planner === "llm" ? (
            <Sparkles className="h-3 w-3" aria-hidden />
          ) : (
            <Cpu className="h-3 w-3" aria-hidden />
          )}
          {decision.planner === "llm" ? "IA" : "Regras"}
        </Badge>
      </header>

      <div className="rounded-md bg-muted/50 px-2.5 py-2">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-medium">{decision.action_label}</span>
          <Badge variant="secondary">{RISK_LABEL[decision.action_risk]}</Badge>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{decision.rationale}</p>
      </div>

      {pending && score.reasons && score.reasons.length > 0 && (
        <div className="text-xs">
          <span className="font-medium">Por que pede aprovação: </span>
          <span className="text-muted-foreground">{score.reasons.join(" ")}</span>
        </div>
      )}
      {result?.message && !pending && <p className="text-xs">{result.message}</p>}
      {decision.error && decision.status !== "executada" && (
        <p className="text-xs text-muted-foreground">{decision.error}</p>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          aria-hidden
        />
        Evidências e score
      </button>
      {open && (
        <div className="space-y-2 border-t pt-2">
          <p className="text-xs text-muted-foreground">{decision.summary}</p>
          <ScoreBar score={score} />
          <ul className="space-y-1.5">
            {shownCitations(decision.citations).map((citation) => (
              <li key={citation.n} className="rounded-md border p-2 text-xs">
                <div className="flex items-center gap-1.5 font-medium">
                  <BookOpen className="h-3.5 w-3.5 text-primary" aria-hidden />
                  {citation.title}
                  <span className="ml-auto font-normal tabular-nums text-muted-foreground">
                    sim. {citation.similarity.toFixed(2)}
                  </span>
                </div>
                <p className="mt-0.5 line-clamp-3 text-muted-foreground">
                  {/* sem o aviso "> fictício" do topo dos documentos: ele tomava as 3 linhas */}
                  {citation.content.replace(/^(>.*\n+)+/, "").replaceAll("**", "")}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {pending && can("prometheus:approve") && (
        <div className="space-y-2 border-t pt-2">
          {rejecting && (
            <Textarea
              rows={2}
              aria-label="Motivo da rejeição"
              placeholder="Motivo (opcional), fica registrado na decisão"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
          <div className="flex items-center gap-2">
            <Button
              size="xs"
              disabled={answer.isPending}
              onClick={() => answer.mutate({ id: decision.id, approve: true })}
            >
              <Check /> Aprovar e executar
            </Button>
            <Button
              size="xs"
              variant="outline"
              disabled={answer.isPending}
              onClick={() =>
                rejecting
                  ? answer.mutate({ id: decision.id, approve: false, note })
                  : setRejecting(true)
              }
            >
              <X /> {rejecting ? "Confirmar rejeição" : "Rejeitar"}
            </Button>
            {decision.expires_at && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                expira {fromNow(decision.expires_at)}
              </span>
            )}
          </div>
        </div>
      )}
    </ToneCard>
  );
}
