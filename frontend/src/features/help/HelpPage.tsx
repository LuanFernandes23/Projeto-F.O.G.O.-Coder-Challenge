import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { MouseEvent } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeSlug from "rehype-slug";
import remarkGfm from "remark-gfm";

import { Input } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

import { filterToc, imageUrl, MANUAL, tableOfContents } from "./manual";

const TOC = tableOfContents(MANUAL);

/** A rolagem fica no <main> do AppShell, não na janela. */
function scroller(): HTMLElement | null {
  return document.getElementById("conteudo");
}

function goTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  history.replaceState(null, "", `#${id}`);
}

function anchorClick(event: MouseEvent<HTMLAnchorElement>, href: string | undefined) {
  if (!href?.startsWith("#")) return;
  event.preventDefault();
  goTo(decodeURIComponent(href.slice(1)));
}

const components: Components = {
  h1: ({ children }) => <h1 className="text-2xl font-semibold tracking-tight">{children}</h1>,
  h2: ({ children, id }) => (
    <h2 id={id} className="scroll-mt-4 border-b pb-2 pt-6 text-xl font-semibold">
      {children}
    </h2>
  ),
  h3: ({ children, id }) => (
    <h3 id={id} className="scroll-mt-4 pt-3 text-base font-semibold">
      {children}
    </h3>
  ),
  p: ({ children }) => <p className="leading-relaxed text-foreground/90">{children}</p>,
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed text-foreground/90">{children}</li>,
  a: ({ children, href }) => (
    <a
      href={href}
      onClick={(event) => anchorClick(event, href)}
      className="text-primary underline underline-offset-2"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/50 text-left">{children}</thead>,
  th: ({ children, style }) => (
    <th style={style} className="px-3 py-2 font-medium">
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="border-t px-3 py-2 align-top text-foreground/90">
      {children}
    </td>
  ),
  img: ({ src, alt }) => {
    const url = imageUrl(typeof src === "string" ? src : undefined);
    if (!url) return null;
    return (
      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        className="block"
        title="Abrir em tamanho real"
      >
        <img
          src={url}
          alt={alt ?? ""}
          loading="lazy"
          className="w-full rounded-lg border shadow-sm"
          width={1440}
          height={900}
        />
      </a>
    );
  },
};

/** Manual do usuário: o mesmo docs/manual.md do repositório, com sumário e busca. */
export function HelpPage() {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<string | undefined>(TOC[0]?.id);
  const entries = useMemo(() => filterToc(TOC, query), [query]);

  // Destaca no sumário a seção que está no topo da leitura.
  useEffect(() => {
    const root = scroller();
    if (!root) return;
    const onScroll = () => {
      const top = root.getBoundingClientRect().top + 96;
      let current = TOC[0]?.id;
      for (const entry of TOC) {
        const element = document.getElementById(entry.id);
        if (element && element.getBoundingClientRect().top <= top) current = entry.id;
      }
      setActive(current);
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, []);

  // Link direto para uma seção (/ajuda#4-prometheus).
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (id) document.getElementById(id)?.scrollIntoView({ block: "start" });
  }, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-4 md:flex-row">
      <aside className="md:sticky md:top-4 md:max-h-[calc(100dvh-5rem)] md:w-64 md:shrink-0 md:self-start md:overflow-y-auto">
        <nav aria-label="Sumário do manual" className="space-y-3">
          <div className="relative">
            <Search
              className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
              aria-hidden
            />
            <Input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar no manual"
              aria-label="Buscar no manual"
              className="pl-8"
            />
          </div>
          {entries.length === 0 ? (
            <p className="px-2 text-sm text-muted-foreground">Nada encontrado para “{query}”.</p>
          ) : (
            <ol className="space-y-0.5 text-sm">
              {entries.map((entry) => (
                <li key={entry.id}>
                  <a
                    href={`#${entry.id}`}
                    onClick={(event) => anchorClick(event, `#${entry.id}`)}
                    aria-current={active === entry.id ? "location" : undefined}
                    className={cn(
                      "block rounded-md px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground",
                      entry.level === 3 && "pl-5 text-[13px]",
                      entry.level === 2 && "font-medium",
                      active === entry.id && "bg-accent text-foreground",
                    )}
                  >
                    {entry.title}
                  </a>
                </li>
              ))}
            </ol>
          )}
        </nav>
      </aside>

      <article className="min-w-0 max-w-3xl flex-1 space-y-4 pb-16 text-[15px]">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSlug]}
          components={components}
        >
          {MANUAL}
        </ReactMarkdown>
      </article>
    </div>
  );
}
