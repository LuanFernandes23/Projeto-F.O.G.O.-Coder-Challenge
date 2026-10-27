// Plugins legados do Leaflet (leaflet.heat) esperam ``window.L``: expõe antes de carregá-los.
import L from "leaflet";

(window as unknown as { L: typeof L }).L = L;
