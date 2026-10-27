"""Preço estimado por milhão de tokens (USD), para acompanhar o consumo. Valores de referência
públicos dos provedores; modelos desconhecidos ficam sem estimativa (custo 0, sinalizado)."""

PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # modelo (prefixo): (entrada, saída)
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "gemini-embedding-001": (0.15, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    match = max((p for p in PRICE_PER_MTOK if model.startswith(p)), key=len, default=None)
    if match is None:
        return 0.0
    price_in, price_out = PRICE_PER_MTOK[match]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
