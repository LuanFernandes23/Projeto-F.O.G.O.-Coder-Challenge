import { describe, expect, it } from "vitest";

import { filterToc, imageUrl, MANUAL, stripWrittenToc, tableOfContents } from "./manual";

const SAMPLE = `# Manual
<!-- sumario -->
## Sumário
1. [A](#1-a)
<!-- /sumario -->

## 1. Primeiros passos
Entrar no sistema.

### Perfis de acesso
Quem pode aprovar o PROMETHEUS.

## 2. Central de Operações
O mapa da cidade.
`;

describe("manual", () => {
  it("tira o sumário escrito e gera os ids do GitHub", () => {
    const toc = tableOfContents(stripWrittenToc(SAMPLE));
    expect(toc.map((e) => [e.level, e.id])).toEqual([
      [2, "1-primeiros-passos"],
      [3, "perfis-de-acesso"],
      [2, "2-central-de-operações"],
    ]);
  });

  it("busca sem acento e mantém o capítulo de uma seção achada", () => {
    const toc = tableOfContents(stripWrittenToc(SAMPLE));
    expect(filterToc(toc, "prometheus").map((e) => e.title)).toEqual([
      "1. Primeiros passos",
      "Perfis de acesso",
    ]);
    expect(filterToc(toc, "operacoes").map((e) => e.title)).toEqual(["2. Central de Operações"]);
    expect(filterToc(toc, "")).toHaveLength(3);
  });

  it("todos os prints e links internos do manual existem", () => {
    const images = [...MANUAL.matchAll(/!\[[^\]]*\]\(([^)]+)\)/g)].map((m) => m[1]);
    expect(images.length).toBeGreaterThan(10);
    expect(images.filter((src) => !imageUrl(src))).toEqual([]);

    const ids = new Set(tableOfContents(MANUAL).map((e) => e.id));
    const anchors = [...MANUAL.matchAll(/\]\(#([^)]+)\)/g)].map((m) => m[1]);
    expect(anchors.filter((id) => !ids.has(id!))).toEqual([]);
  });
});
