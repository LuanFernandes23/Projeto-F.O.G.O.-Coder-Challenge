import { Switch } from "@/components/ui/controls";
import { Label } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { DUTY, EQUIPMENT_STATUS, HEALTH, STATUS_ORDER } from "@/lib/vocabulary";

import type { MapLayers } from "./map/CityMap";
import { MAP_STYLE_LABEL, MAP_STYLES, useMapStyle, type MapStyle } from "./map/map-style";

const LAYER_LABELS: Record<keyof MapLayers, string> = {
  equipment: "Equipamentos",
  agents: "Agentes ao vivo",
  regions: "Saúde das regiões",
  heat: "Calor de falhas (90 dias)",
  risk: "Risco previsto (próximas 24 h)",
};

// Amostras que lembram cada basemap (o "automático" mostra as duas metades).
const SWATCH: Record<MapStyle, string> = {
  auto: "linear-gradient(135deg, #e9e5dc 0 50%, #0f1b2b 50% 100%)",
  claro: "linear-gradient(160deg, #f2efe9 0%, #e4e0d6 55%, #cfe3c4 56%, #dbe9cf 100%), #f2efe9",
  escuro: "linear-gradient(160deg, #0f1b2b 0%, #1b2a3f 55%, #13251f 56%, #0f1b2b 100%)",
  satelite: "linear-gradient(150deg, #3d4a2c 0%, #5f6b45 40%, #8a8065 62%, #2f3a26 100%)",
};

function MapStylePicker() {
  const { style, setStyle } = useMapStyle();
  return (
    <div role="radiogroup" aria-label="Estilo do mapa" className="grid grid-cols-4 gap-2">
      {MAP_STYLES.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={style === option}
          onClick={() => setStyle(option)}
          className="group flex flex-col items-center gap-1 text-[11px] text-muted-foreground aria-checked:text-foreground"
        >
          <span
            className={cn(
              "h-10 w-full rounded-md border-2 transition-all",
              style === option
                ? "border-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.2)]"
                : "border-transparent ring-1 ring-border group-hover:ring-foreground/30",
            )}
            style={{ background: SWATCH[option] }}
            aria-hidden
          />
          {MAP_STYLE_LABEL[option]}
        </button>
      ))}
    </div>
  );
}

export function LayersPanel({
  layers,
  onChange,
}: {
  layers: MapLayers;
  onChange: (layers: MapLayers) => void;
}) {
  return (
    <div className="space-y-5 p-4">
      <section className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground">Estilo do mapa</h3>
        <MapStylePicker />
        <p className="text-[11px] text-muted-foreground">
          Independente do tema da interface. “Automático” acompanha o tema.
        </p>
      </section>

      <section className="space-y-2">
        <h3 className="text-xs font-medium text-muted-foreground">Camadas</h3>
        <div className="divide-y rounded-lg border bg-background/30">
          {(Object.keys(LAYER_LABELS) as (keyof MapLayers)[]).map((key) => (
            <div key={key} className="flex items-center justify-between gap-3 px-3 py-2">
              <Label htmlFor={`layer-${key}`} className="text-sm text-foreground">
                {LAYER_LABELS[key]}
              </Label>
              <Switch
                id={`layer-${key}`}
                checked={layers[key]}
                onCheckedChange={(checked) => onChange({ ...layers, [key]: checked })}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-2 text-xs">
        <h3 className="font-medium text-muted-foreground">Legenda</h3>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
          {STATUS_ORDER.map((status) => {
            const visual = EQUIPMENT_STATUS[status];
            const Icon = visual.icon;
            return (
              <div key={status} className="flex items-center gap-2">
                <Icon
                  className="h-3.5 w-3.5 shrink-0"
                  style={{ color: `hsl(${visual.color})` }}
                  aria-hidden
                />
                {visual.label}
              </div>
            );
          })}
        </div>
        <div className="space-y-1.5 border-t pt-2">
          <div className="flex items-center gap-2">
            <span
              className="h-3 w-3 shrink-0 animate-pulse rounded-full border-2 border-status-maintenance"
              aria-hidden
            />
            Halo pulsante: reparo imediato
          </div>
          <div className="flex items-center gap-2">
            <span
              className="h-3 w-3 shrink-0 rounded-full border-2 border-dashed border-status-maintenance"
              aria-hidden
            />
            Anel tracejado: manutenção vencida ou em até 7 dias
          </div>
          <div className="flex items-center gap-2">
            <span
              className="h-3 w-3 shrink-0 rounded-full border-2 border-dotted border-muted-foreground opacity-60"
              aria-hidden
            />
            Esmaecido: sem comunicação
          </div>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 border-t pt-2">
          {(["disponivel", "em_patrulha", "em_ocorrencia", "em_pausa"] as const).map((s) => (
            <span key={s} className="inline-flex items-center gap-1">
              <span
                className="h-2.5 w-2.5 rotate-45 rounded-[2px]"
                style={{ background: `hsl(${DUTY[s].color})` }}
                aria-hidden
              />
              {DUTY[s].label}
            </span>
          ))}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {(["normal", "atencao", "critico"] as const).map((l) => (
            <span key={l} className="inline-flex items-center gap-1">
              <span
                className="h-2.5 w-4 rounded-sm"
                style={{ background: `hsl(${HEALTH[l].color} / 0.5)` }}
                aria-hidden
              />
              Região {HEALTH[l].label.toLowerCase()}
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}
