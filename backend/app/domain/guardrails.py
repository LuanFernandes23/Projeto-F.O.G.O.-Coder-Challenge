"""Guardrails de conteúdo para a base de conhecimento e o chat (regras puras, testáveis).

- Injeção de prompt: frases que tentam mudar as regras do agente ("ignore as instruções",
  "você agora é", "system prompt", "desative a política"...).
- Segredos: chaves de API, tokens JWT, chaves privadas, senhas em texto.
- Dados pessoais (LGPD): CPF, telefone e e-mail.

Documentos com injeção, segredo ou dado pessoal são recusados. No chat, dados pessoais são
mascarados antes de ir ao modelo e tentativas de injeção são recusadas com explicação.
"""

import re
from dataclasses import dataclass
from enum import StrEnum


class FindingKind(StrEnum):
    INJECAO = "injecao_de_prompt"
    SEGREDO = "segredo"
    DADO_PESSOAL = "dado_pessoal"


@dataclass(frozen=True, slots=True)
class Finding:
    kind: FindingKind
    label: str
    excerpt: str


_INJECTION = [
    (
        r"ignor(e|ar|em)\s+(todas\s+)?(as\s+)?(instru[cç][oõ]es|regras|orienta[cç][oõ]es)",
        "Pede para ignorar instruções",
    ),
    (
        r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)",
        "Pede para ignorar instruções",
    ),
    (
        r"(voc[eê]|tu)\s+(agora\s+)?(é|e|ser[aá])\s+(um|uma|o|a)\s+(novo|nova|outro|outra)",
        "Tenta redefinir o papel do agente",
    ),
    (r"(system|developer)\s*prompt|prompt\s+do\s+sistema", "Menciona o prompt do sistema"),
    (
        r"(desativ|deslig|burl|contorn)\w*\s+(a\s+|as\s+)?(pol[ií]tica|regras|guardrails?|limites?|aprova[cç][aã]o)",
        "Tenta desativar proteções",
    ),
    (
        r"(execute|execut[ae]r?|aprove|aprovar)\s+(automaticamente|sem\s+(aprova[cç][aã]o|humano))",
        "Pede execução sem aprovação",
    ),
    (r"autonomia\s+(m[aá]xima|total|irrestrita)", "Pede autonomia irrestrita"),
    (r"<\s*/?\s*(script|system|assistant)\b", "Contém marcação de papel ou script"),
]
_SECRETS = [
    (r"\bsk-(proj-|ant-)?[A-Za-z0-9_\-]{16,}", "Chave de API (sk-…)"),
    (r"\bAIza[0-9A-Za-z_\-]{30,}", "Chave de API do Google"),
    (r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "Token JWT"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "Chave privada"),
    (r"\b(senha|password|passwd|api[_-]?key|secret)\s*[:=]\s*\S{6,}", "Senha ou segredo em texto"),
]
_PII = [
    (r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b(?=\D|$)", "CPF", "[CPF]"),
    (r"(\(?\b\d{2}\)?\s?)?\b9?\d{4}[-\s]\d{4}\b", "Telefone", "[telefone]"),
    (r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "E-mail", "[e-mail]"),
]


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 20) : min(len(text), end + 20)].replace("\n", " ").strip()


def scan(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for pattern, label in _INJECTION:
        hit = re.search(pattern, text, re.IGNORECASE)
        if hit:
            findings.append(Finding(FindingKind.INJECAO, label, _excerpt(text, *hit.span())))
    for pattern, label in _SECRETS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            # Não ecoa o segredo: mostra só o início.
            findings.append(Finding(FindingKind.SEGREDO, label, m.group(0)[:6] + "…"))
    for pattern, label, _ in _PII:
        m = re.search(pattern, text)
        if m:
            findings.append(Finding(FindingKind.DADO_PESSOAL, label, "…"))
    return findings


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Troca dados pessoais por marcadores; devolve o texto e o que foi removido."""
    removed: list[str] = []
    for pattern, label, token in _PII:
        text, count = re.subn(pattern, token, text)
        if count:
            removed.append(f"{label} ({count})")
    return text, removed


def redact_secrets(text: str) -> str:
    for pattern, _label in _SECRETS:
        text = re.sub(pattern, "[segredo removido]", text, flags=re.IGNORECASE)
    return text


# Política dos documentos criados pela tela (arquivos do repositório passam pela revisão de
# código; a tela não): limites de tamanho e estrutura e teto de autonomia.
DOCUMENT_MAX_CHARS = 20_000
DOCUMENT_MIN_SECTIONS = 1
SCREEN_MAX_AUTONOMY = "medio"
