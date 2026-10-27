// Senha provisória forte, gerada no navegador com crypto.getRandomValues (nunca Math.random).
// Sem caracteres ambíguos (0/O, 1/l/I) para poder ser ditada ao novo usuário.
const GROUPS = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", "@#$%&*-+?"];
const ALL = GROUPS.join("");

function randomIndex(max: number): number {
  // Rejeição para evitar viés do módulo.
  const limit = Math.floor(0x1_0000_0000 / max) * max;
  const buffer = new Uint32Array(1);
  let value: number;
  do {
    crypto.getRandomValues(buffer);
    value = buffer[0] ?? 0;
  } while (value >= limit);
  return value % max;
}

const pick = (chars: string): string => chars.charAt(randomIndex(chars.length));

/** Gera uma senha com ao menos um caractere de cada grupo (maiúscula, minúscula, dígito, símbolo). */
export function generatePassword(length = 14): string {
  const chars = GROUPS.map(pick);
  while (chars.length < length) chars.push(pick(ALL));
  for (let i = chars.length - 1; i > 0; i--) {
    const j = randomIndex(i + 1);
    [chars[i], chars[j]] = [chars[j] ?? "", chars[i] ?? ""];
  }
  return chars.join("");
}

export type PasswordStrength = "fraca" | "media" | "forte";

/** Força estimada pelo tamanho e pela variedade de grupos; só orienta, a regra é da API (≥ 8). */
export function passwordStrength(password: string): PasswordStrength {
  const groups = [/[A-Z]/, /[a-z]/, /\d/, /[^A-Za-z\d]/].filter((re) => re.test(password)).length;
  if (password.length >= 12 && groups >= 3) return "forte";
  if (password.length >= 8 && groups >= 2) return "media";
  return "fraca";
}
