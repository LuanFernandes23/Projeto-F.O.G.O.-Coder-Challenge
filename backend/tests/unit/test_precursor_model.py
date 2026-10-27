"""Classificador de precursores: aprende com desfechos e supera a regra "todo alarme é falha"."""

import random
from datetime import UTC, datetime, timedelta

from app.domain.prediction.precursor_model import LabeledDetection, auc, train
from app.simulator.city import precursor_drift

SPREAD = {"temperature_c": 1.2, "signal_dbm": 2.0, "uptime_pct": 0.25}


def _samples(n: int, seed: int = 3) -> list[LabeledDetection]:
    rng = random.Random(seed)
    start = datetime(2026, 9, 1, tzinfo=UTC)
    samples = []
    for i in range(n):
        real = rng.random() < 0.6
        temp, signal, uptime = precursor_drift(real, rng.random(), rng.uniform(0, 0.45))
        z = {
            "temperature_c": temp / SPREAD["temperature_c"] + rng.gauss(0, 1.6),
            "signal_dbm": signal / SPREAD["signal_dbm"] + rng.gauss(0, 1.6),
            "uptime_pct": uptime / SPREAD["uptime_pct"] + rng.gauss(0, 1.6),
        }
        samples.append(LabeledDetection(start + timedelta(hours=i), z, "semaforo", real))
    return samples


def test_needs_enough_labels_of_both_kinds() -> None:
    assert train(_samples(10)) is None
    only_real = [s for s in _samples(200) if s.real]
    assert train(only_real) is None


def test_learns_which_signals_precede_real_failures() -> None:
    model = train(_samples(300))
    assert model is not None
    metrics = model.metrics
    assert metrics["auc"] > 0.8
    assert metrics["brier"] < metrics["brier_baseline"]
    assert metrics["precision_model"] > metrics["precision_rule"]
    weights = {item["feature"]: item["weight"] for item in model.explain()}
    # Perda de link (sinal/uptime) indica falha real; aquecimento sozinho, alarme falso.
    assert weights["queda de disponibilidade do link"] > 0
    assert weights["aquecimento"] < weights["queda de disponibilidade do link"]
    real_like = model.probability(
        {"temperature_c": 5, "signal_dbm": 6, "uptime_pct": 9}, "semaforo"
    )
    heat_only = model.probability(
        {"temperature_c": 8, "signal_dbm": 1, "uptime_pct": 0.5}, "semaforo"
    )
    assert real_like > 0.7 > 0.3 > heat_only


def test_auc_handles_ties_and_single_class() -> None:
    assert auc([0.9, 0.1], [True, False]) == 1.0
    assert auc([0.5, 0.5], [True, False]) == 0.5
    assert auc([0.5], [True]) is None
