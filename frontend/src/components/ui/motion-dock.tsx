// Dock flutuante de abas: uma pílula de ícones que se expande com mola ao escolher uma aba,
// abrindo um painel cuja altura acompanha o conteúdo. A pílula pode ser arrastada pela alça;
// o painel abre acima ou abaixo conforme o espaço livre. Implementação própria, inspirada no
// padrão "motion tabs menu".
import {
  animate,
  AnimatePresence,
  MotionConfig,
  motion,
  useDragControls,
  useMotionValue,
  type Transition,
} from "motion/react";
import type { LucideIcon } from "lucide-react";
import { GripVertical, X } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";

import { cn } from "@/lib/utils";

export interface DockTab {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Contador no ícone (ex.: alertas abertos, filtros ativos). */
  badge?: number;
  /** Destaca o contador com pulso (ex.: há alerta crítico). */
  alarm?: boolean;
  /** Linha de resumo no cabeçalho do painel. */
  summary?: ReactNode;
  content: ReactNode;
}

const SPRING: Transition = { type: "spring", bounce: 0.2, duration: 0.5 };
const SLIDE = 48;
const GAP = 8; // entre a pílula e o painel
const EDGE = 12; // folga até a borda da área
const HEADER = 58; // altura aproximada do cabeçalho do painel
const PANEL_MAX_WIDTH = 432; // 27rem

interface Geometry {
  placement: "top" | "bottom";
  width: number;
  /** Deslocamento horizontal para o painel não sair da área quando a pílula está num canto. */
  shift: number;
  maxBody: number;
}

const INITIAL_GEOMETRY: Geometry = {
  placement: "top",
  width: PANEL_MAX_WIDTH,
  shift: 0,
  maxBody: 480,
};

/** Direção da troca de aba (−1 esquerda, 1 direita), derivada durante a renderização. */
function useDirection(index: number): number {
  const [previous, setPrevious] = useState(index);
  const [direction, setDirection] = useState(0);
  if (index !== previous) {
    setPrevious(index);
    setDirection(index >= 0 && previous >= 0 ? Math.sign(index - previous) : 0);
  }
  return direction;
}

function readOffset(key: string): { x: number; y: number } {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null") as {
      x?: unknown;
      y?: unknown;
    } | null;
    return typeof value?.x === "number" && typeof value.y === "number"
      ? { x: value.x, y: value.y }
      : { x: 0, y: 0 };
  } catch {
    return { x: 0, y: 0 };
  }
}

/** Posição arrastada da pílula, lembrada entre sessões. */
function usePersistedOffset(key: string) {
  const [initial] = useState(() => readOffset(key));
  const x = useMotionValue(initial.x);
  const y = useMotionValue(initial.y);
  const save = useCallback(() => {
    try {
      localStorage.setItem(key, JSON.stringify({ x: Math.round(x.get()), y: Math.round(y.get()) }));
    } catch {
      /* posição só nesta sessão */
    }
  }, [key, x, y]);
  return { x, y, save };
}

export function MotionDock({
  tabs,
  active,
  onActiveChange,
  label,
  boundsRef,
  storageKey = "fogo-dock-offset",
  className,
}: {
  tabs: DockTab[];
  active: string | null;
  onActiveChange: (id: string | null) => void;
  label: string;
  /** Área onde a pílula pode ser arrastada e onde o painel deve caber. */
  boundsRef: RefObject<HTMLElement>;
  storageKey?: string;
  className?: string;
}) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = tabs.findIndex((tab) => tab.id === active);
  const current = index >= 0 ? tabs[index] : undefined;
  const direction = useDirection(index);
  const dragControls = useDragControls();
  const offset = usePersistedOffset(storageKey);
  const [geometry, setGeometry] = useState<Geometry>(INITIAL_GEOMETRY);

  // Abre do lado com mais espaço e mantém o painel dentro da área.
  const measure = useCallback(() => {
    const bounds = boundsRef.current?.getBoundingClientRect();
    const pill = rootRef.current?.getBoundingClientRect();
    if (!bounds || !pill) return;
    const width = Math.min(PANEL_MAX_WIDTH, bounds.width - EDGE * 2);
    const above = pill.top - bounds.top;
    const below = bounds.bottom - pill.bottom;
    const placement = above >= below ? "top" : "bottom";
    const center = pill.left + pill.width / 2;
    const left = Math.min(
      Math.max(center - width / 2, bounds.left + EDGE),
      bounds.right - EDGE - width,
    );
    const space = (placement === "top" ? above : below) - GAP - EDGE - HEADER;
    const next: Geometry = {
      placement,
      width,
      shift: Math.round(left - (center - width / 2)),
      maxBody: Math.max(140, Math.min(Math.round(space), Math.round(window.innerHeight * 0.62))),
    };
    setGeometry((prev) =>
      prev.placement === next.placement &&
      prev.width === next.width &&
      prev.shift === next.shift &&
      prev.maxBody === next.maxBody
        ? prev
        : next,
    );
  }, [boundsRef]);

  const isOpen = Boolean(current);
  useLayoutEffect(() => {
    if (!isOpen) return undefined;
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [isOpen, measure]);

  const settle = () => {
    offset.save();
    measure();
  };

  // Posição salva pode ficar fora da área (janela menor, outro monitor): traz de volta.
  const { x: offsetX, y: offsetY } = offset;
  useLayoutEffect(() => {
    const clamp = () => {
      const bounds = boundsRef.current?.getBoundingClientRect();
      const pill = rootRef.current?.getBoundingClientRect();
      if (!bounds || !pill) return;
      const dx =
        Math.max(bounds.left + EDGE - pill.left, 0) -
        Math.max(pill.right - (bounds.right - EDGE), 0);
      const dy =
        Math.max(bounds.top + EDGE - pill.top, 0) -
        Math.max(pill.bottom - (bounds.bottom - EDGE), 0);
      if (dx) offsetX.set(offsetX.get() + dx);
      if (dy) offsetY.set(offsetY.get() + dy);
    };
    clamp();
    window.addEventListener("resize", clamp);
    // A própria barra também muda de largura (novas abas, rótulo da aba ativa): reajusta.
    const observer = new ResizeObserver(clamp);
    if (rootRef.current) observer.observe(rootRef.current);
    if (boundsRef.current) observer.observe(boundsRef.current);
    return () => {
      window.removeEventListener("resize", clamp);
      observer.disconnect();
    };
  }, [boundsRef, offsetX, offsetY]);
  const recenter = () => {
    void animate(offset.x, 0, { type: "spring", bounce: 0.2, duration: 0.5 });
    void animate(offset.y, 0, { type: "spring", bounce: 0.2, duration: 0.5, onComplete: settle });
  };

  // Fecha ao clicar fora ou com Esc. Portais (popovers, diálogos, toasts) não contam como "fora".
  useEffect(() => {
    if (!current) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Element | null;
      if (!target || rootRef.current?.contains(target)) return;
      if (target.closest("[data-radix-popper-content-wrapper],[role=dialog],[data-sonner-toast]"))
        return;
      onActiveChange(null);
    };
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (document.querySelector("[role=dialog][data-state=open]")) return;
      onActiveChange(null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [current, onActiveChange]);

  // Setas/Home/End movem o foco entre as abas (padrão WAI-ARIA de tablist).
  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const keys: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      Home: -Infinity,
      End: Infinity,
    };
    const step = keys[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const focused = tabRefs.current.findIndex((el) => el === document.activeElement);
    const next = Number.isFinite(step)
      ? (Math.max(focused, 0) + step + tabs.length) % tabs.length
      : step < 0
        ? 0
        : tabs.length - 1;
    tabRefs.current[next]?.focus();
    const target = tabs[next];
    if (current && target) onActiveChange(target.id);
  };

  const panelId = `${id}-panel`;
  const top = geometry.placement === "top";

  return (
    <MotionConfig reducedMotion="user">
      <div className={cn("pointer-events-none flex justify-center", className)}>
        <motion.div
          ref={rootRef}
          drag
          dragControls={dragControls}
          dragListener={false}
          dragMomentum={false}
          dragElastic={0.06}
          dragConstraints={boundsRef}
          onDrag={measure}
          onDragEnd={settle}
          onDragTransitionEnd={settle}
          style={{ x: offset.x, y: offset.y }}
          className="pointer-events-auto relative"
        >
          <AnimatePresence>
            {current && (
              <motion.div
                key="panel"
                id={panelId}
                role="tabpanel"
                aria-labelledby={`${id}-tab-${current.id}`}
                initial={{ opacity: 0, y: top ? 14 : -14, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{
                  opacity: 0,
                  y: top ? 10 : -10,
                  scale: 0.97,
                  transition: { duration: 0.16 },
                }}
                transition={SPRING}
                style={{
                  width: geometry.width,
                  left: `calc(50% + ${geometry.shift - geometry.width / 2}px)`,
                  transformOrigin: top ? "bottom center" : "top center",
                  ...(top ? { bottom: `calc(100% + ${GAP}px)` } : { top: `calc(100% + ${GAP}px)` }),
                }}
                className="absolute overflow-hidden rounded-2xl border bg-card/95 shadow-[0_24px_60px_-20px_rgb(0_0_0/0.45)] backdrop-blur-xl"
              >
                <PanelHeader tab={current} onClose={() => onActiveChange(null)} />
                <PanelBody tabKey={current.id} direction={direction} maxHeight={geometry.maxBody}>
                  {current.content}
                </PanelBody>
              </motion.div>
            )}
          </AnimatePresence>

          <motion.div
            layout
            transition={SPRING}
            role="tablist"
            aria-label={label}
            onKeyDown={onTabKeyDown}
            className="flex items-center gap-0.5 rounded-full border bg-card/90 p-1.5 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.5)] backdrop-blur-xl"
          >
            <motion.div
              layout="position"
              role="presentation"
              title="Arraste para mover · duplo clique para centralizar"
              onPointerDown={(event) => dragControls.start(event)}
              onDoubleClick={recenter}
              className="grid h-10 w-5 cursor-grab touch-none place-items-center rounded-full text-muted-foreground/60 transition-colors hover:text-foreground active:cursor-grabbing"
            >
              <GripVertical className="h-4 w-4" aria-hidden />
            </motion.div>
            {tabs.map((tab, i) => {
              const selected = tab.id === current?.id;
              const Icon = tab.icon;
              return (
                <motion.button
                  key={tab.id}
                  ref={(el) => {
                    tabRefs.current[i] = el;
                  }}
                  layout
                  type="button"
                  role="tab"
                  id={`${id}-tab-${tab.id}`}
                  aria-selected={selected}
                  aria-expanded={selected}
                  aria-controls={selected ? panelId : undefined}
                  aria-label={tab.badge ? `${tab.label} (${tab.badge})` : tab.label}
                  title={selected ? undefined : tab.label}
                  tabIndex={selected || (!current && i === 0) ? 0 : -1}
                  onClick={() => onActiveChange(selected ? null : tab.id)}
                  whileTap={{ scaleY: 0.8, scaleX: 1.04 }}
                  transition={SPRING}
                  className={cn(
                    "relative flex h-10 items-center rounded-full px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "text-primary-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {selected && (
                    <motion.span
                      layoutId={`${id}-active`}
                      transition={SPRING}
                      className="absolute inset-0 rounded-full bg-primary shadow-[0_6px_16px_-6px_hsl(var(--primary)/0.8)]"
                    />
                  )}
                  <motion.span layout="position" className="relative">
                    <Icon className="h-[18px] w-[18px]" aria-hidden />
                    {tab.badge ? <DockBadge value={tab.badge} alarm={tab.alarm} /> : null}
                  </motion.span>
                  <AnimatePresence initial={false}>
                    {selected && (
                      <motion.span
                        key="label"
                        className="relative overflow-hidden whitespace-nowrap"
                        initial={{ width: 0, opacity: 0, marginLeft: 0 }}
                        animate={{
                          width: "auto",
                          opacity: 1,
                          marginLeft: 8,
                          transition: { ...SPRING, opacity: { delay: 0.08, duration: 0.2 } },
                        }}
                        exit={{
                          width: 0,
                          opacity: 0,
                          marginLeft: 0,
                          transition: { duration: 0.15 },
                        }}
                      >
                        {tab.label}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </motion.button>
              );
            })}
          </motion.div>
        </motion.div>
      </div>
    </MotionConfig>
  );
}

function DockBadge({ value, alarm }: { value: number; alarm?: boolean }) {
  return (
    <span className="absolute -right-2.5 -top-2 flex" aria-hidden>
      {alarm && (
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-60" />
      )}
      <span
        className={cn(
          "relative min-w-[1.05rem] rounded-full px-1 text-center text-[10px] font-bold tabular-nums leading-[1.05rem] ring-2 ring-card",
          alarm
            ? "bg-destructive text-destructive-foreground"
            : "bg-primary text-primary-foreground",
        )}
      >
        {value > 99 ? "99+" : value}
      </span>
    </span>
  );
}

function PanelHeader({ tab, onClose }: { tab: DockTab; onClose: () => void }) {
  return (
    <div className="flex items-center gap-3 border-b px-4 py-2.5">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab.id}
          className="min-w-0 flex-1"
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.14 }}
        >
          <h2 className="text-sm font-semibold leading-tight">{tab.label}</h2>
          {tab.summary && <p className="truncate text-xs text-muted-foreground">{tab.summary}</p>}
        </motion.div>
      </AnimatePresence>
      <button
        type="button"
        onClick={onClose}
        aria-label="Fechar painel"
        className="grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

/** Corpo com altura animada (medida por ResizeObserver) e conteúdo que desliza conforme a direção. */
function PanelBody({
  tabKey,
  direction,
  maxHeight,
  children,
}: {
  tabKey: string;
  direction: number;
  maxHeight: number;
  children: ReactNode;
}) {
  const innerRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");

  useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return undefined;
    const measure = () => setHeight(Math.min(el.offsetHeight, maxHeight));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [maxHeight]);

  return (
    <motion.div
      animate={{ height }}
      transition={SPRING}
      className="fogo-scroll overflow-y-auto overflow-x-hidden overscroll-contain"
    >
      <div ref={innerRef} className="relative">
        <AnimatePresence mode="popLayout" initial={false} custom={direction}>
          <motion.div
            key={tabKey}
            custom={direction}
            variants={{
              enter: (d: number) => ({ x: d * SLIDE, opacity: 0, filter: "blur(3px)" }),
              center: { x: 0, opacity: 1, filter: "blur(0px)" },
              exit: (d: number) => ({ x: d * -SLIDE, opacity: 0, filter: "blur(3px)" }),
            }}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ ...SPRING, opacity: { duration: 0.18 }, filter: { duration: 0.18 } }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
