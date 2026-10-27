import type { AlertSeverity, DutyStatus, EquipmentStatus, HealthLevel } from "@/lib/api/types";
import { cn } from "@/lib/utils";
import { DUTY, EQUIPMENT_STATUS, HEALTH, SEVERITY } from "@/lib/vocabulary";

const badge =
  "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-semibold";

function tone(color: string) {
  return {
    color: `hsl(${color})`,
    backgroundColor: `hsl(${color} / 0.12)`,
    borderColor: `hsl(${color} / 0.35)`,
  };
}

export function EquipmentStatusBadge({
  status,
  className,
}: {
  status: EquipmentStatus;
  className?: string;
}) {
  const visual = EQUIPMENT_STATUS[status];
  const Icon = visual.icon;
  return (
    <span className={cn(badge, className)} style={tone(visual.color)}>
      <Icon className="h-3 w-3" aria-hidden />
      {visual.label}
    </span>
  );
}

export function SeverityBadge({
  severity,
  className,
}: {
  severity: AlertSeverity;
  className?: string;
}) {
  const visual = SEVERITY[severity];
  return (
    <span className={cn(badge, className)} style={tone(visual.color)}>
      {visual.label}
    </span>
  );
}

export function DutyBadge({ status, className }: { status: DutyStatus; className?: string }) {
  const visual = DUTY[status];
  return (
    <span className={cn(badge, className)} style={tone(visual.color)}>
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: `hsl(${visual.color})` }}
        aria-hidden
      />
      {visual.label}
    </span>
  );
}

export function HealthBadge({ level, className }: { level: HealthLevel; className?: string }) {
  const visual = HEALTH[level];
  return (
    <span className={cn(badge, className)} style={tone(visual.color)}>
      {visual.label}
    </span>
  );
}
