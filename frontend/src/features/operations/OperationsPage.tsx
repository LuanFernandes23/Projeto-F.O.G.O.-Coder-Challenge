import {
  AlertOctagon,
  BarChart3,
  Flame,
  Layers,
  Map as MapIcon,
  Send,
  SlidersHorizontal,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { MotionDock, type DockTab } from "@/components/ui/motion-dock";
import { Sheet } from "@/components/ui/overlays";
import { useCityForecast, useDecisions } from "@/features/prediction/api";
import { dayLabel, hourLabel, RISK } from "@/features/prediction/vocabulary";
import { PrometheusPanel } from "@/features/prometheus/PrometheusPanel";
import type { Alert, Dispatch, RegionHealth } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";

import { AlertFeed } from "./AlertFeed";
import {
  useDispatches,
  useEquipmentTypes,
  useHeatmap,
  useMapFeatures,
  useOrganizations,
  useOverview,
  useRegionShapes,
  useRegionsHealth,
} from "./api";
import { DetailDrawer } from "./DetailDrawer";
import { FilterPanel } from "./FilterPanel";
import {
  activeFilterCount,
  EMPTY_FILTERS,
  filterAgents,
  filterEquipment,
  parseFilters,
  toSearchParams,
  type MapFilters,
} from "./filters";
import { KpiBar, type KpiFilter } from "./KpiBar";
import { LayersPanel } from "./LayersPanel";
import { CityMap, type MapLayers, type RegionRisk, type Selection } from "./map/CityMap";
import { MAP_STYLE_LABEL, useMapStyle } from "./map/map-style";
import { DispatchList, Insights, RegionRanking } from "./SidePanels";

const KPI_FILTERS: Record<KpiFilter, Partial<MapFilters>> = {
  todos: {},
  operacionais: { statuses: ["operacional"] },
  indisponiveis: { statuses: ["mau_funcionamento", "em_manutencao", "furtado"] },
  offline: { connectivity: ["offline"] },
  manutencao: { maintenance: ["imediata"] },
  alertas: { onlyAlerts: true },
};

type DockTabId =
  "prometheus" | "alertas" | "regioes" | "equipes" | "analises" | "filtros" | "camadas";

export function OperationsPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(params), [params]);
  const setFilters = useCallback(
    (next: MapFilters) => setParams(toSearchParams(next, params), { replace: true }),
    [params, setParams],
  );
  const [kpi, setKpi] = useState<KpiFilter | null>(null);
  const [layers, setLayers] = useState<MapLayers>({
    equipment: true,
    agents: true,
    regions: true,
    heat: false,
    risk: false,
  });
  const [riskHour, setRiskHour] = useState(0);
  const [selection, setSelection] = useState<Selection>(null);
  const [focus, setFocus] = useState<{
    lat: number;
    lng: number;
    zoom?: number;
    key: number;
  } | null>(null);
  const [dockTab, setDockTab] = useState<string | null>(null);
  const [prometheusOpen, setPrometheusOpen] = useState(false);
  // A aba PROMETHEUS abre um painel lateral (aprovar exige ler score, motivos e citações).
  const changeDockTab = (tab: string | null) => {
    if (tab === "prometheus") {
      setPrometheusOpen(true);
      setDockTab(null);
      return;
    }
    setDockTab(tab);
  };
  const mapAreaRef = useRef<HTMLElement>(null);
  const mapStyle = useMapStyle();

  const overview = useOverview();
  const features = useMapFeatures();
  const regionsHealth = useRegionsHealth();
  const regionShapes = useRegionShapes();
  const types = useEquipmentTypes();
  const organizations = useOrganizations();
  const dispatches = useDispatches();
  const heat = useHeatmap("falhas", 90, layers.heat);
  const forecast = useCityForecast();
  const pendingDecisions = useDecisions(["pendente"]);

  const allEquipment = useMemo(() => features.data?.equipment ?? [], [features.data]);
  const equipment = useMemo(() => filterEquipment(allEquipment, filters), [allEquipment, filters]);
  const agents = useMemo(
    () => filterAgents(features.data?.agents ?? [], filters),
    [features.data, filters],
  );
  const counts = useMemo(() => {
    const statusCounts: Record<string, number> = {};
    const typeCounts: Record<string, number> = {};
    allEquipment.forEach((e) => {
      statusCounts[e.status] = (statusCounts[e.status] ?? 0) + 1;
      typeCounts[e.type_code] = (typeCounts[e.type_code] ?? 0) + 1;
    });
    return { statusCounts, typeCounts };
  }, [allEquipment]);

  const flyTo = (lat: number, lng: number, zoom?: number) =>
    setFocus({ lat, lng, zoom, key: Date.now() });

  const applyKpi = (next: KpiFilter) => {
    const same = kpi === next;
    setKpi(same ? null : next);
    setFilters({
      ...EMPTY_FILTERS,
      onlyOnDuty: filters.onlyOnDuty,
      ...(same ? {} : KPI_FILTERS[next]),
    });
    if (next === "alertas" && !same) setDockTab("alertas");
  };

  // Ao abrir um equipamento ou agente no mapa, o painel do PROMETHEUS dá lugar ao detalhe.
  useEffect(() => {
    if (selection) setPrometheusOpen(false);
  }, [selection]);

  const locateAlert = (alert: Alert) => {
    if (!alert.equipment) return;
    flyTo(alert.equipment.latitude, alert.equipment.longitude);
    setSelection({ kind: "equipment", id: alert.equipment.equipment_id });
    setDockTab(null); // o ponto fica no centro do mapa, onde o painel estaria
  };
  const locateDispatch = (dispatch: Dispatch) => {
    flyTo(dispatch.target.latitude, dispatch.target.longitude, 15);
    setSelection({ kind: "agent", id: dispatch.agent_id });
    setDockTab(null);
  };
  const selectRegion = (region: RegionHealth) => {
    setFilters({ ...filters, regions: [region.region_id] });
  };

  const riskCells = useMemo(() => {
    const data = forecast.data?.ready ? forecast.data.data : undefined;
    if (!data) return null;
    const byRegion: RegionRisk = {};
    let at = "";
    for (const region of data.regions) {
      const cell = data.cells.filter((c) => c.region === region.code)[riskHour];
      if (!cell) continue;
      at = cell.at;
      byRegion[region.code] = {
        level: cell.level,
        index: cell.index,
        probability: cell.probability,
      };
    }
    return { byRegion, at };
  }, [forecast.data, riskHour]);
  const riskLabel = riskCells?.at ? `${dayLabel(riskCells.at)} ${hourLabel(riskCells.at)}` : "";
  const pendingCount = pendingDecisions.data?.length ?? 0;

  const o = overview.data;
  const critical = o?.alerts_by_severity.critica ?? 0;
  const activeDispatches = dispatches.data?.length ?? 0;
  const activeFilters = activeFilterCount(filters);

  const tabs: (DockTab & { id: DockTabId })[] = [
    {
      id: "prometheus",
      label: "PROMETHEUS",
      icon: Flame,
      badge: pendingCount,
      alarm: pendingCount > 0,
      summary: pendingCount
        ? `${pendingCount} ação(ões) aguardando sua aprovação`
        : "Agente autônomo: decisões e aprovações",
      content: null,
    },
    {
      id: "alertas",
      label: "Alertas",
      icon: AlertOctagon,
      badge: o?.alerts_open,
      alarm: critical > 0,
      summary: o
        ? `${formatNumber(o.alerts_open)} abertos · ${critical} crítico(s) · ${o.alerts_sla_breached} fora do SLA`
        : undefined,
      content: <AlertFeed onLocate={locateAlert} />,
    },
    {
      id: "regioes",
      label: "Regiões",
      icon: MapIcon,
      summary: "Da pior para a melhor · clique para filtrar o mapa",
      content: <RegionRanking regions={regionsHealth.data} onSelect={selectRegion} />,
    },
    {
      id: "equipes",
      label: "Equipes",
      icon: Send,
      badge: activeDispatches,
      summary: activeDispatches
        ? `${activeDispatches} despacho(s) em andamento`
        : "Nenhum despacho em andamento",
      content: <DispatchList onLocate={locateDispatch} />,
    },
    {
      id: "analises",
      label: "Análises",
      icon: BarChart3,
      summary: "Falhas, reparos e situação por tipo",
      content: <Insights overview={o} />,
    },
    {
      id: "filtros",
      label: "Filtros",
      icon: SlidersHorizontal,
      badge: activeFilters,
      summary: `${formatNumber(equipment.length)} de ${formatNumber(allEquipment.length)} equipamentos no mapa`,
      content: (
        <FilterPanel
          filters={filters}
          onChange={(next) => {
            setKpi(null);
            setFilters(next);
          }}
          types={types.data ?? []}
          regions={regionShapes.data ?? []}
          organizations={organizations.data ?? []}
          statusCounts={counts.statusCounts}
          typeCounts={counts.typeCounts}
        />
      ),
    },
    {
      id: "camadas",
      label: "Camadas",
      icon: Layers,
      summary: `Mapa ${MAP_STYLE_LABEL[mapStyle.resolved].toLowerCase()} · legenda`,
      content: <LayersPanel layers={layers} onChange={setLayers} />,
    },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <KpiBar overview={o} active={kpi} onSelect={applyKpi} />
      <section
        ref={mapAreaRef}
        className="relative min-h-0 flex-1 border-t"
        aria-label="Mapa da cidade"
      >
        <CityMap
          equipment={equipment}
          agents={agents}
          regionShapes={regionShapes.data ?? []}
          regionHealth={regionsHealth.data ?? []}
          heat={heat.data ?? []}
          dispatches={dispatches.data ?? []}
          layers={layers}
          selection={selection}
          focus={focus}
          onSelect={setSelection}
          onRegionClick={() => undefined}
          risk={riskCells?.byRegion ?? null}
          riskLabel={riskLabel}
        />
        <div className="pointer-events-none absolute left-3 top-3 z-[500] hidden rounded-full border bg-card/90 px-3 py-1 text-xs shadow-md backdrop-blur md:block">
          <span className="font-semibold tabular-nums">{equipment.length}</span>
          <span className="text-muted-foreground"> de {allEquipment.length} equipamentos · </span>
          <span className="font-semibold tabular-nums">{agents.length}</span>
          <span className="text-muted-foreground"> agentes</span>
          {activeFilters > 0 && <span className="text-primary"> · filtrado</span>}
        </div>
        {layers.risk && riskCells && (
          <div className="absolute left-1/2 top-3 z-[600] w-[min(26rem,calc(100%-2rem))] -translate-x-1/2 rounded-xl border bg-card/95 px-4 py-2.5 shadow-lg backdrop-blur">
            <div className="flex items-baseline justify-between gap-2 text-xs">
              <label htmlFor="risk-hour" className="font-medium">
                Risco previsto: <span className="capitalize">{riskLabel}</span>
              </label>
              <span className="text-muted-foreground">
                {riskHour === 0 ? "agora" : `daqui a ${riskHour} h`}
              </span>
            </div>
            <input
              id="risk-hour"
              type="range"
              min={0}
              max={23}
              value={riskHour}
              onChange={(e) => setRiskHour(Number(e.target.value))}
              className="mt-1.5 w-full accent-[hsl(var(--primary))]"
              aria-valuetext={riskLabel}
            />
            <ul className="mt-1 flex justify-between text-[10px] text-muted-foreground" aria-hidden>
              {Object.values(RISK).map((r) => (
                <li key={r.label} className="flex items-center gap-1">
                  <span
                    className="h-2 w-3 rounded-sm"
                    style={{ background: `hsl(${r.color} / ${0.2 + r.fill})` }}
                  />
                  {r.label}
                </li>
              ))}
            </ul>
          </div>
        )}
        <MotionDock
          label="Painéis da central"
          tabs={tabs}
          active={dockTab}
          onActiveChange={changeDockTab}
          boundsRef={mapAreaRef}
          className="absolute inset-x-0 bottom-5 z-[1001]"
        />
      </section>

      <Sheet
        open={prometheusOpen}
        onOpenChange={setPrometheusOpen}
        title={
          <span className="flex items-center gap-2">
            <Flame className="h-4 w-4 text-[hsl(var(--brand-fire))]" aria-hidden /> PROMETHEUS
          </span>
        }
        description="Decisões do agente: o que ele fez sozinho e o que espera a sua aprovação."
        className="max-w-xl"
      >
        <PrometheusPanel />
      </Sheet>
      <DetailDrawer
        selection={selection}
        equipment={allEquipment}
        agents={features.data?.agents ?? []}
        onClose={() => setSelection(null)}
      />
    </div>
  );
}
