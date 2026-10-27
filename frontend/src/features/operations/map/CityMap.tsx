import "./leaflet-global";
import "leaflet.heat";

import dayjs from "dayjs";
import L from "leaflet";
import { memo, useEffect, useMemo } from "react";
import { GeoJSON, MapContainer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import type {
  Dispatch,
  HeatPoint,
  MapAgent,
  MapEquipment,
  Region,
  RegionHealth,
} from "@/lib/api/types";
import { DUTY, EQUIPMENT_STATUS, HEALTH, ROLE } from "@/lib/vocabulary";
import type { RiskLevel } from "@/features/prediction/types";
import { RISK } from "@/features/prediction/vocabulary";

import { agentIcon, clusterIcon, equipmentIcon } from "./icons";
import { Basemap, useMapStyle } from "./map-style";

export const MARILIA_CENTER: [number, number] = [-22.2139, -49.9458];

export interface MapLayers {
  equipment: boolean;
  agents: boolean;
  regions: boolean;
  heat: boolean;
  risk: boolean;
}

/** Risco previsto por região (código) para o horário escolhido no controle deslizante. */
export type RegionRisk = Record<string, { level: RiskLevel; index: number; probability: number }>;

export type Selection = { kind: "equipment" | "agent"; id: string } | null;

interface CityMapProps {
  equipment: MapEquipment[];
  agents: MapAgent[];
  regionShapes: Region[];
  regionHealth: RegionHealth[];
  heat: HeatPoint[];
  dispatches: Dispatch[];
  layers: MapLayers;
  selection: Selection;
  focus: { lat: number; lng: number; zoom?: number; key: number } | null;
  onSelect: (selection: Selection) => void;
  onRegionClick: (regionId: string) => void;
  risk?: RegionRisk | null;
  riskLabel?: string;
}

function isDue(item: MapEquipment, today: dayjs.Dayjs): boolean {
  if (!item.next_maintenance_date || item.maintenance_need === "imediata") return false;
  return !dayjs(item.next_maintenance_date).isAfter(today.add(7, "day"), "day");
}

const EquipmentMarkers = memo(function EquipmentMarkers({
  items,
  selectedId,
  onSelect,
}: {
  items: MapEquipment[];
  selectedId: string | undefined;
  onSelect: CityMapProps["onSelect"];
}) {
  const today = dayjs();
  return (
    <MarkerClusterGroup
      chunkedLoading
      maxClusterRadius={45}
      showCoverageOnHover={false}
      spiderfyOnMaxZoom
      zoomToBoundsOnClick={false}
      iconCreateFunction={clusterIcon}
      onClick={(event: L.LeafletEvent) => {
        // Regra: grupo "empilhado" (< 40 m) abre em leque; senão, aproxima.
        const cluster = event.propagatedFrom as L.MarkerCluster;
        const bounds = cluster.getBounds();
        if (bounds.getNorthEast().distanceTo(bounds.getSouthWest()) < 40) cluster.spiderfy();
        else cluster.zoomToBounds({ padding: [40, 40] });
      }}
    >
      {items.map((item) => (
        <Marker
          key={item.id}
          position={[item.lat, item.lng]}
          icon={equipmentIcon(item, { due: isDue(item, today), selected: item.id === selectedId })}
          keyboard
          title={`${item.serial_number} — ${EQUIPMENT_STATUS[item.status].label}`}
          eventHandlers={{ click: () => onSelect({ kind: "equipment", id: item.id }) }}
        >
          <Tooltip className="fogo-tooltip" direction="top">
            <strong>{item.serial_number}</strong> · {EQUIPMENT_STATUS[item.status].label}
            {item.open_alerts > 0 && ` · ${item.open_alerts} alerta(s)`}
          </Tooltip>
        </Marker>
      ))}
    </MarkerClusterGroup>
  );
});

function AgentMarkers({
  agents,
  onSelect,
}: {
  agents: MapAgent[];
  onSelect: CityMapProps["onSelect"];
}) {
  return (
    <>
      {agents.map((agent) => (
        <Marker
          key={agent.id}
          position={[agent.lat, agent.lng]}
          icon={agentIcon(agent)}
          zIndexOffset={500}
          title={`${agent.full_name} — ${DUTY[agent.duty_status].label}`}
          eventHandlers={{ click: () => onSelect({ kind: "agent", id: agent.id }) }}
        >
          <Tooltip className="fogo-tooltip" direction="top">
            <strong>{agent.full_name}</strong> · {ROLE[agent.role].short} ·{" "}
            {DUTY[agent.duty_status].label}
            {!agent.live && " · posição da base"}
          </Tooltip>
        </Marker>
      ))}
    </>
  );
}

function RiskLayer({ shapes, risk, label }: { shapes: Region[]; risk: RegionRisk; label: string }) {
  return (
    <>
      {shapes.map((region) => {
        const item = risk[region.code];
        if (!region.geometry || !item) return null;
        const visual = RISK[item.level];
        const color = `hsl(${visual.color})`;
        return (
          <GeoJSON
            key={`risk:${region.id}:${item.level}:${item.index}`}
            data={region.geometry as unknown as GeoJSON.GeoJsonObject}
            style={{
              color,
              weight: 2,
              dashArray: "6 4",
              fillColor: color,
              fillOpacity: visual.fill,
            }}
          >
            <Tooltip className="fogo-tooltip" sticky>
              <strong>{region.name}</strong> · {label}: risco {visual.label.toLowerCase()} (índice{" "}
              {item.index}, {Math.round(item.probability * 100)}% de chance de ocorrência)
            </Tooltip>
          </GeoJSON>
        );
      })}
    </>
  );
}

function RegionsLayer({
  shapes,
  health,
  onRegionClick,
}: {
  shapes: Region[];
  health: RegionHealth[];
  onRegionClick: (regionId: string) => void;
}) {
  const map = useMap();
  const byId = useMemo(() => new Map(health.map((h) => [h.region_id, h])), [health]);
  return (
    <>
      {shapes.map((region) => {
        const regionHealth = byId.get(region.id);
        const color = `hsl(${HEALTH[regionHealth?.level ?? "normal"].color})`;
        if (!region.geometry) return null;
        return (
          <GeoJSON
            // A chave muda com o nível: o react-leaflet não atualiza o estilo sozinho.
            key={`${region.id}:${regionHealth?.level}:${regionHealth?.score}`}
            data={region.geometry as unknown as GeoJSON.GeoJsonObject}
            style={{
              color,
              weight: 2,
              fillColor: color,
              fillOpacity: { normal: 0.03, atencao: 0.08, critico: 0.14 }[
                regionHealth?.level ?? "normal"
              ],
            }}
            eventHandlers={{
              click: (event) => {
                map.fitBounds((event.target as L.GeoJSON).getBounds(), { padding: [30, 30] });
                onRegionClick(region.id);
              },
            }}
          >
            <Tooltip className="fogo-tooltip" sticky>
              <strong>{region.name}</strong>
              {regionHealth &&
                ` · saúde ${regionHealth.score.toFixed(0)} · ${HEALTH[regionHealth.level].label}`}
            </Tooltip>
          </GeoJSON>
        );
      })}
    </>
  );
}

function HeatLayer({ points }: { points: HeatPoint[] }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return undefined;
    const max = Math.max(...points.map((p) => p.weight));
    const layer = L.heatLayer(
      points.map((p) => [p.latitude, p.longitude, p.weight / max] as [number, number, number]),
      { radius: 28, blur: 22, maxZoom: 16, minOpacity: 0.3 },
    ).addTo(map);
    return () => {
      layer.remove();
    };
  }, [map, points]);
  return null;
}

function DispatchRoutes({ dispatches, agents }: { dispatches: Dispatch[]; agents: MapAgent[] }) {
  const byId = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);
  return (
    <>
      {dispatches.map((dispatch) => {
        const agent = byId.get(dispatch.agent_id);
        if (!agent || dispatch.status === "no_local") return null;
        return (
          <Polyline
            key={dispatch.id}
            positions={[
              [agent.lat, agent.lng],
              [dispatch.target.latitude, dispatch.target.longitude],
            ]}
            pathOptions={{
              color: "hsl(var(--primary))",
              weight: 3,
              className: "fogo-dispatch-line",
            }}
          />
        );
      })}
    </>
  );
}

function FocusController({ focus }: { focus: CityMapProps["focus"] }) {
  const map = useMap();
  useEffect(() => {
    if (focus) map.flyTo([focus.lat, focus.lng], focus.zoom ?? 17, { duration: 0.8 });
  }, [map, focus]);
  return null;
}

export function CityMap(props: CityMapProps) {
  const mapStyle = useMapStyle();
  return (
    // O MapContainer congela o className na criação; a classe do estilo fica num invólucro.
    <div className={`h-full w-full ${mapStyle.className}`}>
      <MapContainer
        center={MARILIA_CENTER}
        zoom={13}
        minZoom={11}
        maxZoom={19}
        zoomControl={false}
        className="h-full w-full"
        aria-label="Mapa da cidade com equipamentos e agentes"
      >
        <Basemap style={mapStyle.resolved} />
        {props.layers.risk && props.risk ? (
          <RiskLayer shapes={props.regionShapes} risk={props.risk} label={props.riskLabel ?? ""} />
        ) : (
          props.layers.regions && (
            <RegionsLayer
              shapes={props.regionShapes}
              health={props.regionHealth}
              onRegionClick={props.onRegionClick}
            />
          )
        )}
        {props.layers.heat && <HeatLayer points={props.heat} />}
        {props.layers.equipment && (
          <EquipmentMarkers
            items={props.equipment}
            selectedId={props.selection?.kind === "equipment" ? props.selection.id : undefined}
            onSelect={props.onSelect}
          />
        )}
        {props.layers.agents && (
          <>
            <DispatchRoutes dispatches={props.dispatches} agents={props.agents} />
            <AgentMarkers agents={props.agents} onSelect={props.onSelect} />
          </>
        )}
        <FocusController focus={props.focus} />
        <ZoomButtons />
      </MapContainer>
    </div>
  );
}

function ZoomButtons() {
  const map = useMap();
  return (
    <div className="leaflet-bottom leaflet-right" style={{ marginBottom: 28 }}>
      <div className="leaflet-control flex flex-col overflow-hidden rounded-md border bg-card shadow-md">
        <button
          type="button"
          className="h-8 w-8 text-lg hover:bg-accent"
          aria-label="Aproximar"
          onClick={() => map.zoomIn()}
        >
          +
        </button>
        <button
          type="button"
          className="h-8 w-8 border-t text-lg hover:bg-accent"
          aria-label="Afastar"
          onClick={() => map.zoomOut()}
        >
          −
        </button>
        <button
          type="button"
          className="h-8 w-8 border-t text-[10px] font-semibold hover:bg-accent"
          aria-label="Centralizar na cidade"
          onClick={() => map.flyTo(MARILIA_CENTER, 13)}
        >
          ⌂
        </button>
      </div>
    </div>
  );
}
