import { useCallback, useSyncExternalStore } from "react";
import { TileLayer } from "react-leaflet";

import { useTheme } from "@/lib/theme";

/**
 * Estilo do mapa, independente do tema da interface. "auto" acompanha o tema; os demais
 * fixam o basemap (um operador pode querer satélite com a interface clara, por exemplo).
 */
export type MapStyle = "auto" | "claro" | "escuro" | "satelite";
export type ResolvedMapStyle = Exclude<MapStyle, "auto">;

export const MAP_STYLES: MapStyle[] = ["auto", "claro", "escuro", "satelite"];
export const MAP_STYLE_LABEL: Record<MapStyle, string> = {
  auto: "Automático",
  claro: "Claro",
  escuro: "Escuro",
  satelite: "Satélite",
};

const OSM = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">Colaboradores do OpenStreetMap</a>',
  maxNativeZoom: 19,
};

// O escuro reaproveita os tiles do OSM com um filtro CSS só na camada de tiles
// (.fogo-map--escuro em index.css): o basemap escuro da CARTO passou a exigir chave.
const BASEMAPS: Record<ResolvedMapStyle, typeof OSM> = {
  claro: OSM,
  escuro: OSM,
  satelite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution:
      "Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    maxNativeZoom: 18,
  },
};

const KEY = "fogo-map-style";
const listeners = new Set<() => void>();

function read(): MapStyle {
  try {
    const value = localStorage.getItem(KEY);
    return MAP_STYLES.includes(value as MapStyle) ? (value as MapStyle) : "auto";
  } catch {
    return "auto";
  }
}

let current: MapStyle = read();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setMapStyle(style: MapStyle) {
  current = style;
  try {
    localStorage.setItem(KEY, style);
  } catch {
    /* preferência só nesta sessão */
  }
  listeners.forEach((listener) => listener());
}

/** Estilo escolhido + estilo efetivo (com "auto" resolvido pelo tema) e a classe CSS do mapa. */
export function useMapStyle() {
  const { theme } = useTheme();
  const style = useSyncExternalStore(subscribe, () => current);
  const resolved: ResolvedMapStyle =
    style === "auto" ? (theme === "dark" ? "escuro" : "claro") : style;
  const set = useCallback((next: MapStyle) => setMapStyle(next), []);
  return { style, resolved, setStyle: set, className: `fogo-map--${resolved}` };
}

/** Camada de tiles do estilo efetivo; remonta ao trocar (a atribuição muda junto). */
export function Basemap({ style }: { style: ResolvedMapStyle }) {
  const basemap = BASEMAPS[style];
  return (
    <TileLayer
      key={style}
      url={basemap.url}
      attribution={basemap.attribution}
      maxNativeZoom={basemap.maxNativeZoom}
      maxZoom={19}
    />
  );
}
