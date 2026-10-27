// Endereço com autopreenchimento por CEP + minimapa para marcar a coordenada exata.
import { Loader2, LocateFixed, Search } from "lucide-react";
import { useState } from "react";
import { MapContainer, Marker, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Input, Label } from "@/components/ui/primitives";
import { MARILIA_CENTER } from "@/features/operations/map/CityMap";
import { Basemap, useMapStyle } from "@/features/operations/map/map-style";
import { api, ApiError } from "@/lib/api/client";
import type { Address, CepLookup } from "@/lib/api/types";

export interface AddressValue {
  cep: string;
  street: string;
  reference: string;
  neighborhood: string;
  city: string;
  uf: Address["uf"];
}

export interface PointValue {
  latitude: number;
  longitude: number;
}

const UFS =
  "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" ");

const pickerIcon = L.divIcon({
  className: "",
  html: '<div class="fogo-pin" style="--pin-color:hsl(var(--primary))"></div>',
  iconSize: [30, 30],
  iconAnchor: [15, 15],
});

function ClickToPlace({ onPick }: { onPick: (point: PointValue) => void }) {
  useMapEvents({ click: (e) => onPick({ latitude: e.latlng.lat, longitude: e.latlng.lng }) });
  return null;
}

export function maskCep(value: string): string {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  return digits.length > 5 ? `${digits.slice(0, 5)}-${digits.slice(5)}` : digits;
}

export function LocationFields({
  address,
  point,
  onAddressChange,
  onPointChange,
  errors,
  idPrefix,
}: {
  address: AddressValue;
  point: PointValue | null;
  onAddressChange: (address: AddressValue) => void;
  onPointChange: (point: PointValue) => void;
  errors: Record<string, string>;
  idPrefix: string;
}) {
  const [loading, setLoading] = useState(false);
  const mapStyle = useMapStyle();
  const set = (key: keyof AddressValue, value: string) =>
    onAddressChange({ ...address, [key]: value } as AddressValue);

  const lookup = async () => {
    setLoading(true);
    try {
      const result = await api<CepLookup>(`/addresses/cep/${address.cep.replace(/\D/g, "")}`);
      onAddressChange({
        ...address,
        street: result.street ?? address.street,
        neighborhood: result.neighborhood ?? address.neighborhood,
        city: result.city,
        uf: result.uf,
      });
      if (result.location) onPointChange(result.location);
      toast.success(`Endereço preenchido (${result.source})`, {
        description: result.location
          ? "Coordenada sugerida pelo CEP — ajuste no mapa."
          : "Marque o ponto exato no mapa.",
      });
    } catch (error) {
      toast.error(
        error instanceof ApiError && error.status === 503
          ? "Serviços de CEP indisponíveis — preencha manualmente."
          : (error as Error).message,
      );
    } finally {
      setLoading(false);
    }
  };

  const field = (key: keyof AddressValue, label: string, props: Record<string, unknown> = {}) => (
    <div className="space-y-1.5" key={key}>
      <Label htmlFor={`${idPrefix}-${key}`}>{label}</Label>
      <Input
        id={`${idPrefix}-${key}`}
        value={address[key]}
        aria-invalid={Boolean(errors[key])}
        onChange={(e) => set(key, e.target.value)}
        {...props}
      />
      {errors[key] && (
        <p className="text-xs text-destructive" role="alert">
          {errors[key]}
        </p>
      )}
    </div>
  );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="grid content-start gap-4 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor={`${idPrefix}-cep`}>CEP</Label>
          <div className="flex gap-2">
            <Input
              id={`${idPrefix}-cep`}
              inputMode="numeric"
              placeholder="00000-000"
              value={address.cep}
              aria-invalid={Boolean(errors.cep)}
              onChange={(e) => set("cep", maskCep(e.target.value))}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void lookup();
                }
              }}
            />
            <Button
              type="button"
              variant="secondary"
              onClick={() => void lookup()}
              disabled={loading || address.cep.replace(/\D/g, "").length !== 8}
            >
              {loading ? <Loader2 className="animate-spin" /> : <Search />} Buscar CEP
            </Button>
          </div>
          {errors.cep && <p className="text-xs text-destructive">{errors.cep}</p>}
        </div>
        <div className="sm:col-span-2">{field("street", "Logradouro")}</div>
        {field("reference", "Número ou referência", {
          placeholder: 'Ex.: "181", "oposto ao 181", "KM 203", "S/N"',
        })}
        {field("neighborhood", "Bairro")}
        {field("city", "Cidade")}
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-uf`}>UF</Label>
          <Select
            id={`${idPrefix}-uf`}
            value={address.uf}
            onValueChange={(v) => set("uf", v)}
            options={UFS.map((u) => ({ value: u, label: u }))}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <Label>Coordenada (clique no mapa para marcar)</Label>
          <span className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
            <LocateFixed className="h-3 w-3" />
            {point ? `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}` : "não marcada"}
          </span>
        </div>
        <div
          className={`h-72 overflow-hidden rounded-md border ${mapStyle.className}`}
          aria-invalid={Boolean(errors.location)}
        >
          <MapContainer
            center={point ? [point.latitude, point.longitude] : MARILIA_CENTER}
            zoom={14}
            className="h-full w-full"
          >
            <Basemap style={mapStyle.resolved} />
            <ClickToPlace onPick={onPointChange} />
            {point && (
              <Marker
                position={[point.latitude, point.longitude]}
                icon={pickerIcon}
                draggable
                eventHandlers={{
                  dragend: (e) => {
                    const latlng = (e.target as L.Marker).getLatLng();
                    onPointChange({ latitude: latlng.lat, longitude: latlng.lng });
                  },
                }}
              />
            )}
          </MapContainer>
        </div>
        {errors.location && <p className="text-xs text-destructive">{errors.location}</p>}
      </div>
    </div>
  );
}
