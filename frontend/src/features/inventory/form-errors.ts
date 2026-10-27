// Converte erros da API (problem+json) em mensagens por campo do formulário.
import { ApiError } from "@/lib/api/client";

export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const result: Record<string, string> = {};
  error.fieldErrors.forEach(({ field, message }) => {
    if (!field) return;
    const parts = field.split(".");
    // "address.cep" → "cep"; "attributes.max_speed_kmh" → "max_speed_kmh"; "location" → "location"
    const key = parts.length > 1 ? (parts[parts.length - 1] ?? field) : field;
    result[key] ??= message.replace(/^Value error, /, "");
  });
  const extraField = error.problem.field;
  if (typeof extraField === "string") result[extraField] ??= error.message;
  return result;
}
