// Conexão SSE com a Central: aplica posições ao vivo e invalida consultas afetadas.
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { MapFeatures } from "@/lib/api/types";
import { tokenStore } from "@/lib/auth-store";

import {
  applyPositions,
  staleQueriesFor,
  type LiveEvent,
  type PositionUpdate,
} from "./live-reducer";
import { playAlertSound } from "./sound";

export type LiveStatus = "connecting" | "live" | "offline";

const INVALIDATION_DEBOUNCE_MS = 800;
const MAX_RETRY_MS = 15_000;

class RetriableError extends Error {}

export function useLiveEvents(options: { soundEnabled: boolean }): LiveStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const sound = useRef(options.soundEnabled);
  sound.current = options.soundEnabled;

  useEffect(() => {
    const controller = new AbortController();
    const pending = new Map<string, string[]>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retry = 1000;

    const flush = () => {
      pending.forEach((queryKey) => void queryClient.invalidateQueries({ queryKey }));
      pending.clear();
    };
    const schedule = (keys: string[][]) => {
      keys.forEach((key) => pending.set(key.join("|"), key));
      clearTimeout(timer);
      timer = setTimeout(flush, INVALIDATION_DEBOUNCE_MS);
    };
    const resync = () =>
      schedule([["map-features"], ["overview"], ["alerts"], ["regions-health"], ["dispatches"]]);

    const handle = (event: LiveEvent) => {
      if (event.type === "agents.positions") {
        const positions = (event.data.positions ?? []) as PositionUpdate[];
        queryClient.setQueryData<MapFeatures>(["map-features"], (old) =>
          applyPositions(old, positions, new Date().toISOString()),
        );
        return;
      }
      if (event.type === "alert.opened" && event.data.severity === "critica") {
        toast.error(String(event.data.title ?? "Alerta crítico"), {
          description: "Novo alerta crítico na cidade.",
          duration: 8000,
        });
        if (sound.current) playAlertSound();
      }
      if (event.type === "prometheus.decision") {
        const title = String(event.data.title ?? "");
        if (event.data.status === "pendente") {
          toast.warning("PROMETHEUS pede aprovação", { description: title, duration: 8000 });
        } else if (event.data.status === "executada" && event.data.mode === "automatica") {
          toast.success("PROMETHEUS agiu sozinho", { description: title });
        }
      }
      if (event.type === "fault.averted") {
        toast.success("Falha evitada", {
          description: "O equipamento recebeu intervenção antes de falhar.",
        });
      }
      schedule(staleQueriesFor(event));
    };

    void fetchEventSource("/api/v1/stream", {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${tokenStore.get() ?? ""}`, Accept: "text/event-stream" },
      // Fecha ao esconder a aba e reconecta ao voltar.
      openWhenHidden: false,
      async onopen(response) {
        if (!response.ok) {
          if (response.status === 401) tokenStore.expire();
          throw new RetriableError(`SSE ${response.status}`);
        }
        retry = 1000;
        setStatus("live");
        resync();
      },
      onmessage(message) {
        if (!message.data) return;
        if (message.event === "resync") {
          resync();
          return;
        }
        if (message.event === "ready") return;
        try {
          handle(JSON.parse(message.data) as LiveEvent);
        } catch {
          /* mensagem malformada: ignora */
        }
      },
      onclose() {
        setStatus("connecting");
        throw new RetriableError("conexão encerrada");
      },
      onerror() {
        setStatus("offline");
        retry = Math.min(retry * 2, MAX_RETRY_MS);
        return retry; // tenta novamente com backoff exponencial
      },
    });

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [queryClient]);

  return status;
}
