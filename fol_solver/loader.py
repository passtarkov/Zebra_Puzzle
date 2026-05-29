import csv
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .fact_filter import FactFilter


TIMESERIES_METRICS = ['m1', 'm1_raw', 'm2', 'm4', 'm6', 'm8', 'm9']


@dataclass
class MetricsBundle:
    m1: dict[int, dict[int, float]] = field(default_factory=dict)
    m1_raw: dict[int, dict[int, float]] = field(default_factory=dict)
    m2: dict[int, dict[int, float]] = field(default_factory=dict)
    m3: dict[int, Optional[int]] = field(default_factory=dict)
    m4: dict[int, dict[int, float]] = field(default_factory=dict)
    m5_raw: dict[int, dict[float, float]] = field(default_factory=dict)
    m5_fol: dict[int, dict[float, float]] = field(default_factory=dict)
    m6: dict[int, dict[int, float]] = field(default_factory=dict)
    m8: dict[int, dict[int, float]] = field(default_factory=dict)
    m9: dict[int, dict[int, float]] = field(default_factory=dict)

    def get(self, metric_name: str, agent_id: int, t: int) -> float:
        series = getattr(self, metric_name, None)
        if not isinstance(series, dict) or agent_id not in series:
            return 0.0
        agent_series = series[agent_id]
        if t in agent_series:
            return agent_series[t]
        candidates = [k for k in agent_series if k <= t]
        if not candidates:
            return 0.0
        return agent_series[max(candidates)]

    def at(self, agent_id: int, t: int) -> dict[str, float]:
        return {name: self.get(name, agent_id, t) for name in TIMESERIES_METRICS}

    def agents(self) -> list[int]:
        return sorted(self.m1.keys())

    def timesteps(self, metric_name: str = 'm1') -> list[int]:
        series = getattr(self, metric_name, {})
        if not isinstance(series, dict):
            return []
        return sorted({t for agent_data in series.values() for t in agent_data})


def _load_timeseries_csv(path: str) -> dict[int, dict[int, float]]:
    result: dict[int, dict[int, float]] = defaultdict(dict)
    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)
        for row in reader:
            result[int(row[0])][int(row[1])] = float(row[2])
    return dict(result)


def _load_m3_csv(path: str) -> dict[int, Optional[int]]:
    result: dict[int, Optional[int]] = {}
    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)
        for row in reader:
            aid = int(row[0])
            result[aid] = int(row[2]) if row[2] else None
    return result


def _load_m5_csv(path: str) -> dict[int, dict[float, float]]:
    result: dict[int, dict[float, float]] = defaultdict(dict)
    with open(path, encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        next(reader)
        for row in reader:
            result[int(row[0])][float(row[1])] = float(row[2])
    return dict(result)


def load_metrics(metrics_dir: str) -> MetricsBundle:
    bundle = MetricsBundle()
    for name in TIMESERIES_METRICS:
        path = os.path.join(metrics_dir, f"{name}.csv")
        setattr(bundle, name, _load_timeseries_csv(path))
    bundle.m3 = _load_m3_csv(os.path.join(metrics_dir, "m3.csv"))
    bundle.m5_raw = _load_m5_csv(os.path.join(metrics_dir, "m5_raw.csv"))
    bundle.m5_fol = _load_m5_csv(os.path.join(metrics_dir, "m5_fol.csv"))
    return bundle


class FilteredMetrics:
    def __init__(
        self,
        observer_csv: str,
        logs_dir: str,
        zebra_csv: str,
        fact_filter: FactFilter,
        metrics: Optional[list[str]] = None,
        max_horizon: int = 100,
    ):
        self._data = compute_filtered_metrics(
            observer_csv=observer_csv,
            logs_dir=logs_dir,
            zebra_csv=zebra_csv,
            fact_filter=fact_filter,
            metrics=metrics,
            max_horizon=max_horizon,
        )
        # cache: {metric_name: {agent_id: sorted list of timestamps}}
        # speeds up step-function lookup
        self._sorted_ts: dict[str, dict[int, list[int]]] = {
            m: {aid: sorted(ts for ts, _ in series)
                for aid, series in agents.items()}
            for m, agents in self._data.items()
        }

    def get(self, metric_name: str, agent_id: int, t: int) -> float:
        agents = self._data.get(metric_name)
        if agents is None or agent_id not in agents:
            return 0.0
        series = agents[agent_id]
        if not series:
            return 0.0
        sorted_ts = self._sorted_ts[metric_name][agent_id]
        # find last timestamp <= t via bisect
        import bisect
        pos = bisect.bisect_right(sorted_ts, t) - 1
        if pos < 0:
            return 0.0
        target_t = sorted_ts[pos]
        # series is list[(t, value)], find value at target_t
        # we know it's there because target_t came from this series
        for ts, v in series:
            if ts == target_t:
                return v
        return 0.0

    def at(self, agent_id: int, t: int) -> dict[str, float]:
        return {m: self.get(m, agent_id, t) for m in self._data}

    def agents(self) -> list[int]:
        all_aids: set[int] = set()
        for agents in self._data.values():
            all_aids.update(agents.keys())
        return sorted(all_aids)

    def timesteps(self, metric_name: str = 'm1') -> list[int]:
        agents = self._data.get(metric_name, {})
        return sorted({t for series in agents.values() for t, _ in series})

    def metric_names(self) -> list[str]:
        return list(self._data.keys())


def compute_filtered_metrics(
    observer_csv: str,
    logs_dir: str,
    zebra_csv: str,
    fact_filter: FactFilter,
    metrics: Optional[list[str]] = None,
    max_horizon: int = 100,
) -> dict[str, dict[int, list[tuple[int, float]]]]:
    from .log_parser import (
        load_domain, parse_observer_csv, reconstruct_world_states,
        load_all_knowledge, get_knowledge_at,
    )
    from .z3_solver import infer_knowledge
    from .metrics import compute_m1, compute_m4, compute_m6, compute_m9

    if metrics is None:
        metrics = ['m1', 'm4', 'm6', 'm9']

    domain = load_domain(zebra_csv)
    events = parse_observer_csv(observer_csv, domain)
    world_states = reconstruct_world_states(events, domain)
    k_raw = load_all_knowledge(logs_dir, domain.agent_ids)

    k_raw_times = {t for series in k_raw.values() for t in series}
    timesteps = sorted(set(world_states.keys()) | k_raw_times)

    k_fol: dict[int, dict] = {aid: {} for aid in domain.agent_ids}
    for aid in domain.agent_ids:
        series = k_raw.get(aid, {})
        for t in timesteps:
            raw = get_knowledge_at(series, t)
            if raw is not None:
                k_fol[aid][t] = infer_knowledge(raw, domain)

    results: dict[str, dict[int, list[tuple[int, float]]]] = {}
    if 'm1' in metrics:
        results['m1'] = compute_m1(world_states, k_fol, timesteps, domain,
                                    fact_filter=fact_filter)
    if 'm4' in metrics:
        results['m4'] = compute_m4(world_states, k_fol, timesteps, domain,
                                    fact_filter=fact_filter)
    if 'm6' in metrics:
        results['m6'] = compute_m6(events, world_states, k_fol, timesteps,
                                    domain, fact_filter=fact_filter,
                                    max_horizon=max_horizon)
    if 'm9' in metrics:
        results['m9'] = compute_m9(world_states, k_raw, k_fol, timesteps,
                                    domain, fact_filter=fact_filter)
    return results