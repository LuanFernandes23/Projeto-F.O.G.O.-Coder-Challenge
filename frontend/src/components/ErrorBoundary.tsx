import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface State {
  error: Error | null;
}

/** Falha numa tela não derruba o app inteiro: mostra o erro e permite tentar de novo. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Erro de interface", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        role="alert"
        className="m-6 rounded-lg border border-destructive/40 bg-destructive/5 p-6"
      >
        <div className="flex items-center gap-2 font-semibold text-destructive">
          <AlertTriangle className="h-5 w-5" /> Algo deu errado nesta tela
        </div>
        <p className="mt-2 text-sm text-muted-foreground">{this.state.error.message}</p>
        <Button className="mt-4" variant="outline" onClick={() => this.setState({ error: null })}>
          <RotateCcw /> Tentar novamente
        </Button>
      </div>
    );
  }
}
