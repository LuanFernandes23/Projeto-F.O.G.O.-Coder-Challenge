import dayjs from "dayjs";
import "dayjs/locale/pt-br";
import relativeTime from "dayjs/plugin/relativeTime";

dayjs.extend(relativeTime);
dayjs.locale("pt-br");

export const formatNumber = (value: number): string => value.toLocaleString("pt-BR");

export const formatPercent = (value: number, digits = 1): string =>
  `${value.toLocaleString("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits })}%`;

export const formatDate = (value: string | null | undefined): string =>
  value ? dayjs(value).format("DD/MM/YYYY") : "—";

export const formatDateTime = (value: string | null | undefined): string =>
  value ? dayjs(value).format("DD/MM/YYYY HH:mm") : "—";

export const fromNow = (value: string | null | undefined): string =>
  value ? dayjs(value).fromNow() : "—";

export function formatDistance(meters: number): string {
  return meters < 1000
    ? `${Math.round(meters)} m`
    : `${(meters / 1000).toFixed(1).replace(".", ",")} km`;
}

/** "1h 05min", "12min", "-8min" (estourado) a partir de segundos. */
export function formatDuration(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const total = Math.abs(Math.round(seconds / 60));
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (hours >= 24) return `${sign}${Math.floor(hours / 24)}d ${hours % 24}h`;
  return hours ? `${sign}${hours}h ${String(minutes).padStart(2, "0")}min` : `${sign}${minutes}min`;
}
