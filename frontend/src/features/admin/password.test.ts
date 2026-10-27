import { describe, expect, it } from "vitest";

import { generatePassword, passwordStrength } from "./password";

describe("generatePassword", () => {
  it("gera senhas fortes, sem caracteres ambíguos e diferentes a cada chamada", () => {
    const passwords = Array.from({ length: 50 }, () => generatePassword());
    passwords.forEach((p) => {
      expect(p).toHaveLength(14);
      expect(p).toMatch(/[A-Z]/);
      expect(p).toMatch(/[a-z]/);
      expect(p).toMatch(/\d/);
      expect(p).toMatch(/[^A-Za-z\d]/);
      expect(p).not.toMatch(/[0O1lI]/);
      expect(passwordStrength(p)).toBe("forte");
    });
    expect(new Set(passwords).size).toBe(passwords.length);
  });
});

describe("passwordStrength", () => {
  it.each([
    ["abc", "fraca"],
    ["abcdefgh", "fraca"],
    ["abcdefg1", "media"],
    ["Abcdefghij1!", "forte"],
  ])("%s → %s", (password, expected) => {
    expect(passwordStrength(password)).toBe(expected);
  });
});
