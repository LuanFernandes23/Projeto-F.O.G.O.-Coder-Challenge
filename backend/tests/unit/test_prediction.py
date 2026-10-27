"""Motor preditivo: o modelo precisa redescobrir padrões conhecidos e vencer as linhas de base."""

import ast
import pathlib
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.domain.prediction.anomaly import (
    Baseline,
    binomial_upper_tail,
    regional_surprise,
    score_device,
)
from app.domain.prediction.backtest import calibration, evaluate
from app.domain.prediction.equipment_risk import DeviceHistory, fit_equipment_risk
from app.domain.prediction.reinforcement import RegionWindow, recommend
from app.domain.prediction.risk_model import (
    EVENT_KINDS,
    EventWindow,
    Installation,
    Occurrence,
    build_grid,
    fit,
)
from app.domain.prediction.trends import project, theil_sen

REGIONS = ("centro", "norte", "sul")
TRUE_REGION = {"centro": 1.0, "norte": 2.0, "sul": 0.5}
START = date(2025, 1, 6)
DAYS = 280


def _true_hour(hour: int) -> float:
    return 3.0 if 18 <= hour <= 22 else 0.5


def _synthetic(seed: int = 7) -> tuple[list[Installation], list[Occurrence], list[EventWindow]]:
    rng = np.random.default_rng(seed)
    installations = [
        Installation(region, "camera", START - timedelta(days=1))
        for region in REGIONS
        for _ in range(100)
    ]
    sundays = [START + timedelta(days=6 + 7 * week) for week in range(DAYS // 7)]
    events = [
        EventWindow(
            "esporte",
            "norte",
            datetime(d.year, d.month, d.day, 15),
            datetime(d.year, d.month, d.day, 20),
        )
        for d in sundays
    ]
    occurrences: list[Occurrence] = []
    for day in range(DAYS):
        current = START + timedelta(days=day)
        for region in REGIONS:
            for hour in range(24):
                when = datetime(current.year, current.month, current.day, hour)
                rate = 100 * 0.0004 * TRUE_REGION[region] * _true_hour(hour)
                if any(e.region == region and e.starts_at <= when < e.ends_at for e in events):
                    rate *= 3.0
                for _ in range(rng.poisson(rate)):
                    occurrences.append(Occurrence(when, region, "camera"))
    return installations, occurrences, events


def test_model_recovers_region_and_hour_factors() -> None:
    installations, occurrences, events = _synthetic()
    grid = build_grid(
        REGIONS, START, START + timedelta(days=DAYS), installations, occurrences, events
    )
    model = fit(grid)

    region = dict(zip(model.regions, model.region, strict=True))
    assert region["norte"] / region["centro"] == pytest.approx(2.0, rel=0.15)
    assert region["sul"] / region["centro"] == pytest.approx(0.5, rel=0.2)
    monday_20h = model.rate(0, 1, datetime(2025, 5, 5, 20), 0, 1.0)
    monday_3h = model.rate(0, 1, datetime(2025, 5, 5, 3), 0, 1.0)
    assert monday_20h / monday_3h == pytest.approx(6.0, rel=0.35)
    assert model.hour[20] / model.hour[3] == pytest.approx(6.0, rel=0.35)
    sport = EVENT_KINDS.index("esporte")
    assert model.event[1, sport] == pytest.approx(3.0, rel=0.3)


def test_backtest_beats_naive_baselines_and_is_calibrated() -> None:
    installations, occurrences, events = _synthetic(seed=11)
    split = START + timedelta(days=DAYS - 28)
    train = build_grid(REGIONS, START, split, installations, occurrences, events)
    test = build_grid(
        REGIONS, split, START + timedelta(days=DAYS), installations, occurrences, events
    )
    metrics = evaluate(fit(train), train, test)

    assert metrics["skill_vs_mean"] > 0.1
    assert metrics["skill_vs_hour"] > 0.0
    assert metrics["top20_capture"] > 0.3
    calib = metrics["calibration"]
    assert calib["observed"] == sorted(calib["observed"])  # monótona


def test_outlier_days_are_excluded_from_training() -> None:
    installations, occurrences, events = _synthetic()
    burst_day = START + timedelta(days=100)
    occurrences += [
        Occurrence(datetime(burst_day.year, burst_day.month, burst_day.day, 12), "sul", "camera")
    ] * 400
    grid = build_grid(
        REGIONS, START, START + timedelta(days=DAYS), installations, occurrences, events
    )
    model = fit(grid)
    assert burst_day.isoformat() in model.excluded_days
    region = dict(zip(model.regions, model.region, strict=True))
    assert region["sul"] < region["centro"]


def test_calibration_maps_probability_to_observed_frequency() -> None:
    probabilities = np.array([0.02] * 100 + [0.5] * 100)
    hits = np.array([0.0] * 98 + [1.0] * 2 + [1.0] * 70 + [0.0] * 30)
    calib = calibration(probabilities, hits)
    assert calib.calibrate(0.02) == pytest.approx(0.02)
    assert calib.calibrate(0.5) == pytest.approx(0.7)


def test_overdue_preventive_effect_is_measured() -> None:
    today = date(2026, 1, 1)
    histories = []
    for i in range(60):
        overdue = i % 2 == 0
        done = (
            (date(2025, 4, 1), date(2025, 9, 1))
            if overdue
            else (date(2025, 3, 1), date(2025, 6, 1), date(2025, 9, 1), date(2025, 12, 1))
        )
        failures = (tuple(datetime(2025, 7, 10 + k, 10) for k in range(4)) if overdue else ()) + (
            datetime(2025, 2, 1, 10),
        )
        histories.append(DeviceHistory("semaforo", date(2025, 1, 1), failures, done, 90))
    model = fit_equipment_risk(histories, today)
    assert model.overdue_factor > 2.0


def test_device_anomaly_needs_two_signals_or_a_strong_one() -> None:
    baselines = {
        "temperature_c": Baseline(30.0, 0.6, 12),
        "signal_dbm": Baseline(-70.0, 1.0, 12),
        "uptime_pct": Baseline(99.6, 0.05, 12),
    }
    normal = score_device({"temperature_c": 30.5, "signal_dbm": -71, "uptime_pct": 99.5}, baselines)
    assert not normal.is_anomaly
    precursor = score_device(
        {"temperature_c": 38.0, "signal_dbm": -82, "uptime_pct": 97.0}, baselines
    )
    assert precursor.is_anomaly
    assert precursor.score > normal.score
    assert {s["metric"] for s in precursor.signals} == {"temperature_c", "signal_dbm", "uptime_pct"}


def test_regional_surprise_flags_only_significant_excess() -> None:
    assert binomial_upper_tail(0, 10, 0.3) == 1.0
    share = {"centro": 0.4, "norte": 0.3, "sul": 0.3}
    assert regional_surprise({"centro": 8, "norte": 6, "sul": 6}, share) == []
    flagged = regional_surprise({"centro": 3, "norte": 15, "sul": 2}, share)
    assert [f["region"] for f in flagged] == ["norte"]


def test_reinforcement_moves_agents_toward_risk_and_events() -> None:
    result = recommend(
        [
            RegionWindow("centro", 1.0, staffed=10),
            RegionWindow("norte", 6.0, staffed=4),
            RegionWindow("leste", 1.0, staffed=6, event_public=12_000, event_names=("Jogo",)),
        ]
    )
    rows = {r["region"]: r for r in result["regions"]}
    assert rows["norte"]["gap"] > 0
    assert rows["leste"]["recommended"] >= 6  # 12 mil pessoas → ao menos 6 agentes
    assert any(m["to"] == "norte" and m["from"] == "centro" for m in result["moves"])


def test_trend_projection_detects_decline() -> None:
    assert theil_sen([1, 2, 3, 4])[0] == pytest.approx(1.0)
    series = [(date(2026, 1, 1) + timedelta(days=i), 98 - 0.2 * i) for i in range(30)]
    result = project(series, threshold=90)
    assert result["status"] == "queda"
    assert result["crosses_on"] is not None


def test_prediction_engine_never_reads_simulation_parameters() -> None:
    """O modelo aprende só do histórico: importar o seed/simulador seria trapaça."""
    package = pathlib.Path(__file__).parents[2] / "app" / "domain" / "prediction"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(("app.seed", "app.simulator")), path.name
