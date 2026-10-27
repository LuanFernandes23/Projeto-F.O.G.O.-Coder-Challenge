// Formato dos retratos de previsão (JSON calculado pelo scheduler; ver prediction_service.py).

export type RiskLevel = "baixo" | "moderado" | "alto" | "muito_alto";

export interface Factor {
  factor: string;
  multiplier: number;
}

export interface RiskCell {
  region: string;
  at: string; // horário local (ISO sem fuso)
  expected: number;
  probability: number;
  index: number;
  level: RiskLevel;
}

export interface Hotspot {
  region: string;
  region_name: string;
  starts_at: string;
  ends_at: string;
  expected: number;
  ratio: number;
  peak_at: string;
  factors: Factor[];
  events: string[];
}

export interface EquipmentRisk {
  equipment_id: string;
  serial_number: string;
  type_code: string;
  type_name: string;
  region: string | null;
  neighborhood: string;
  overdue: boolean;
  probability_72h: number;
  factors: Factor[];
}

export interface ReinforcementRow {
  region: string;
  region_name: string;
  expected_occurrences: number;
  risk_share: number;
  staffed: number;
  recommended: number;
  gap: number;
  event_public: number;
  events: string[];
  reason: string;
  handling_minutes: number | null;
}

export interface ReinforcementBlock {
  starts_at: string;
  ends_at: string;
  total_staff: number;
  regions: ReinforcementRow[];
  moves: { from: string; to: string; agents: number }[];
}

export interface TrendSeries {
  type_code: string;
  series: { date: string; value: number }[];
  slope_per_week: number;
  current_fitted?: number;
  crosses_on: string | null;
  status: "queda" | "alta" | "estavel" | "dados_insuficientes";
  projection?: { date: string; value: number }[];
}

export interface Calibration {
  edges: number[];
  observed: number[];
  predicted: number[];
  counts: number[];
}

export interface Backtest {
  test_days: number;
  test_events: number;
  deviance: { model: number; baseline_mean: number; baseline_hour: number };
  skill_vs_mean: number;
  skill_vs_hour: number;
  mae: { model: number; baseline_mean: number; baseline_hour: number };
  top20_capture: number;
  calibration: Calibration;
}

export interface CityEventItem {
  name: string;
  kind: string;
  region: string | null;
  expected_public: number;
  starts_at: string;
  ends_at: string;
}

export interface CityForecast {
  generated_at: string;
  model: {
    id: number;
    fitted_at: string;
    observed_events: number;
    excluded_days: string[];
    factors: {
      region: { region: string; name: string; multiplier: number }[];
      hour: number[];
      week: Record<string, number[][]>;
      month: Record<string, number[]>;
      event: Record<string, Record<string, number>>;
    };
    equipment: {
      type_rate_per_day: Record<string, number>;
      type_trend: Record<string, number>;
      overdue_factor: number;
      overdue_evidence: Record<string, number>;
    };
  };
  backtest: Backtest;
  regions: { code: string; name: string }[];
  cells: RiskCell[];
  explain: Record<string, { group: string; factors: Factor[] }>;
  hotspots: Hotspot[];
  equipment_risk: EquipmentRisk[];
  reinforcement: ReinforcementBlock[];
  trends: TrendSeries[];
  events: CityEventItem[];
  averted_last_7_days: { total: number; by_prometheus: number };
}

export interface AnomalySignal {
  metric: string;
  label: string;
  value: number;
  baseline: number;
  z: number;
}

export interface AnomalySnapshot {
  generated_at: string;
  devices: {
    equipment_id: string;
    serial_number: string;
    type_code: string;
    region: string | null;
    neighborhood: string;
    score: number;
    signals: AnomalySignal[];
    p_real?: number | null;
  }[];
  regional: {
    region: string;
    region_name?: string;
    observed: number;
    expected: number;
    ratio: number;
    p_value: number;
  }[];
  quality: {
    detections_confirmed: number;
    detections_averted: number;
    false_alarms: number;
    pending: number;
    decided: number;
    precision: number | null;
    recall: number | null;
    mean_lead_minutes: number | null;
    live_failures: number;
  };
  learning?: {
    active: boolean;
    labels: number;
    min_labels: number;
    metrics: {
      auc?: number | null;
      precision_model?: number | null;
      precision_rule?: number | null;
      brier?: number;
      brier_baseline?: number;
    };
    explain: { feature: string; weight: number; odds_ratio: number }[];
  };
}

export interface Snapshot<T> {
  ready: boolean;
  data: T;
}
