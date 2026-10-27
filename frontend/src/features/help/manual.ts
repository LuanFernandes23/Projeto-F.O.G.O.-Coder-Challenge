import GithubSlugger from "github-slugger";

import source from "@docs/manual.md?raw";

// O manual é um arquivo só (docs/manual.md): o GitHub o exibe direto e esta tela o renderiza.
const IMAGES = import.meta.glob<string>("@docs/img/manual/*.webp", {
  eager: true,
  query: "?url",
  import: "default",
});

const TOC_BLOCK = /<!-- sumario -->[\s\S]*?<!-- \/sumario -->\n*/;

/** O sumário escrito no arquivo serve ao GitHub; aqui o sumário é a barra lateral. */
export function stripWrittenToc(markdown: string): string {
  return markdown.replace(TOC_BLOCK, "");
}

export const MANUAL = stripWrittenToc(source);

export interface TocEntry {
  id: string;
  title: string;
  level: 2 | 3;
  /** Texto da seção (até o próximo título), para a busca. */
  text: string;
}

/** Títulos ## e ### com os mesmos ids que o rehype-slug gera (o slugger do GitHub). */
export function tableOfContents(markdown: string): TocEntry[] {
  const slugger = new GithubSlugger();
  const entries: TocEntry[] = [];
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (line.startsWith("```")) fenced = !fenced;
    const heading = fenced ? null : /^(#{1,6})\s+(.+?)\s*$/.exec(line);
    if (!heading) {
      const last = entries[entries.length - 1];
      if (last) last.text += `${line}\n`;
      continue;
    }
    const level = heading[1]!.length;
    const title = heading[2]!;
    const id = slugger.slug(title); // todo título conta, para os sufixos de repetidos baterem
    if (level === 2 || level === 3) entries.push({ id, title, level, text: "" });
  }
  return entries;
}

export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

/** Seções cujo título ou texto contém a busca; um ### achado leva junto o ## dele. */
export function filterToc(entries: TocEntry[], query: string): TocEntry[] {
  const q = normalize(query.trim());
  if (!q) return entries;
  const keep = new Set<TocEntry>();
  let parent: TocEntry | undefined;
  for (const entry of entries) {
    if (entry.level === 2) parent = entry;
    if (normalize(`${entry.title}\n${entry.text}`).includes(q)) {
      keep.add(entry);
      if (entry.level === 3 && parent) keep.add(parent);
    }
  }
  return entries.filter((entry) => keep.has(entry));
}

/** "img/manual/central.webp" (caminho do GitHub) → URL do arquivo no build. */
export function imageUrl(src: string | undefined): string | undefined {
  const name = src?.split("/").pop();
  if (!name) return undefined;
  const key = Object.keys(IMAGES).find((path) => path.endsWith(`/${name}`));
  return key ? IMAGES[key] : undefined;
}
