// Armazenamento do token de acesso (sessionStorage: some ao fechar a aba).
// A autorização real é sempre verificada pela API; aqui só decidimos o que exibir.
const KEY = "fogo-token";
type Listener = () => void;
const listeners = new Set<Listener>();

function read(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export const tokenStore = {
  get: read,
  set(token: string): void {
    try {
      sessionStorage.setItem(KEY, token);
    } catch {
      /* armazenamento indisponível: segue só em memória durante a sessão */
    }
    listeners.forEach((l) => l());
  },
  clear(): void {
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* ignora */
    }
    listeners.forEach((l) => l());
  },
  /** Sessão expirada (401): limpa e avisa os ouvintes (o app volta ao login). */
  expire(): void {
    this.clear();
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};
