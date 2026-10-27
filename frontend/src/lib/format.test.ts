import { describe, expect, it } from "vitest";

import { formatDistance, formatDuration, formatPercent } from "./format";

describe("formatação pt-BR", () => {
  it("distância", () => {
    expect(formatDistance(401)).toBe("401 m");
    expect(formatDistance(2345)).toBe("2,3 km");
  });

  it("duração do SLA, inclusive estourado", () => {
    expect(formatDuration(59 * 60)).toBe("59min");
    expect(formatDuration(3900)).toBe("1h 05min");
    expect(formatDuration(-480)).toBe("-8min");
    expect(formatDuration(26 * 3600)).toBe("1d 2h");
  });

  it("percentual", () => {
    expect(formatPercent(89.94)).toBe("89,9%");
  });
});
