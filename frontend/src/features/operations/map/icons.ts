// Ícones do mapa (L.divIcon) com cache: o mesmo visual reaproveita a mesma instância.
import L from "leaflet";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import type { EquipmentStatus, MapAgent, MapEquipment } from "@/lib/api/types";
import { DUTY, EQUIPMENT_STATUS, ROLE, SEVERITY, STATUS_ORDER, typeIcon } from "@/lib/vocabulary";

const svgCache = new Map<string, string>();
const iconCache = new Map<string, L.DivIcon>();

function svg(key: string, render: () => string): string {
  let value = svgCache.get(key);
  if (!value) {
    value = render();
    svgCache.set(key, value);
  }
  return value;
}

const typeSvg = (code: string) =>
  svg(`type:${code}`, () =>
    renderToStaticMarkup(createElement(typeIcon(code), { strokeWidth: 2.4, "aria-hidden": true })),
  );

export interface EquipmentIconOptions extends L.DivIconOptions {
  status: EquipmentStatus;
}

export function equipmentIcon(
  item: MapEquipment,
  flags: { due: boolean; selected: boolean },
): L.DivIcon {
  const urgent = item.maintenance_need === "imediata";
  const offline = item.connectivity === "offline";
  const badge = item.top_alert_severity ? SEVERITY[item.top_alert_severity].color : null;
  const key = [item.type_code, item.status, urgent, flags.due, offline, badge, flags.selected].join(
    "|",
  );
  const cached = iconCache.get(key);
  if (cached) return cached;

  const classes = [
    "fogo-pin",
    urgent && "fogo-pin--urgent",
    flags.due && "fogo-pin--due",
    offline && "fogo-pin--offline",
    flags.selected && "fogo-pin--selected",
  ]
    .filter(Boolean)
    .join(" ");
  const badgeHtml = badge
    ? `<span class="fogo-pin__badge" style="--badge-color:hsl(${badge})"></span>`
    : "";
  const options: EquipmentIconOptions = {
    className: "",
    html: `<div class="${classes}" style="--pin-color:hsl(${EQUIPMENT_STATUS[item.status].color})">${typeSvg(item.type_code)}${badgeHtml}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    tooltipAnchor: [0, -16],
    status: item.status,
  };
  const icon = L.divIcon(options);
  iconCache.set(key, icon);
  return icon;
}

/** Cluster com anel colorido pela proporção de status (leitura do estado de relance). */
export function clusterIcon(cluster: L.MarkerCluster): L.DivIcon {
  const markers = cluster.getAllChildMarkers();
  const counts = new Map<EquipmentStatus, number>();
  markers.forEach((marker) => {
    const status = (marker.options.icon?.options as EquipmentIconOptions | undefined)?.status;
    if (status) counts.set(status, (counts.get(status) ?? 0) + 1);
  });
  let start = 0;
  const stops: string[] = [];
  STATUS_ORDER.forEach((status) => {
    const count = counts.get(status) ?? 0;
    if (!count) return;
    const end = start + (count / markers.length) * 360;
    stops.push(`hsl(${EQUIPMENT_STATUS[status].color}) ${start}deg ${end}deg`);
    start = end;
  });
  const total = markers.length;
  const size = total < 10 ? 36 : total < 50 ? 44 : 52;
  const unavailable = total - (counts.get("operacional") ?? 0);
  return L.divIcon({
    className: "",
    html: `<div class="fogo-cluster" style="width:${size}px;height:${size}px;--ring-gradient:conic-gradient(${stops.join(",")})" aria-label="${total} equipamentos, ${unavailable} fora de operação"><span>${total}</span></div>`,
    iconSize: [size, size],
  });
}

export function agentIcon(agent: MapAgent): L.DivIcon {
  const key = `agent:${agent.role}:${agent.duty_status}:${agent.live}`;
  const cached = iconCache.get(key);
  if (cached) return cached;
  const roleSvg = svg(`role:${agent.role}`, () =>
    renderToStaticMarkup(
      createElement(ROLE[agent.role].icon, { strokeWidth: 2.4, "aria-hidden": true }),
    ),
  );
  const icon = L.divIcon({
    className: `fogo-agent${agent.live ? "" : " fogo-agent--stale"}`,
    html: `<div class="fogo-agent__body" style="--agent-color:hsl(${DUTY[agent.duty_status].color})">${roleSvg}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    tooltipAnchor: [0, -16],
  });
  iconCache.set(key, icon);
  return icon;
}
