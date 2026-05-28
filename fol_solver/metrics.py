import bisect
import random
from collections import defaultdict
from typing import Optional, Sequence

from .fact_filter import FactFilter
from .log_parser import Domain, _TimestampedDict, get_knowledge_at, get_world_state_at
from .world_state import AgentState, KnowledgeSnapshot, WorldSnapshot

_ATTRS = ['house', 'pet', 'location']


def _count_filtered_facts(
    k: KnowledgeSnapshot,
    w: WorldSnapshot,
    agent_ids: list[int],
    attributes: list[str],
    fact_filter: Optional[FactFilter],
) -> tuple[int, int]:
    correct = denominator = 0
    for aid in agent_ids:
        true_s: Optional[AgentState] = w.agents.get(aid)
        known_s: Optional[AgentState] = k.known_agents.get(aid)
        if true_s is None:
            continue
        for attr in attributes:
            true_val = getattr(true_s, attr)
            if fact_filter is not None and not fact_filter.matches(aid, attr, true_val):
                continue
            denominator += 1
            if known_s is not None and getattr(known_s, attr) == true_val:
                correct += 1
    return correct, denominator


def compute_m1(
    world_states: dict[int, WorldSnapshot],
    knowledge: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
    fact_filter: Optional[FactFilter] = None,
) -> dict[int, list[tuple[int, float]]]:
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id in domain.agent_ids:
        vals = []
        for t in timesteps:
            w = get_world_state_at(world_states, t)
            k = get_knowledge_at(knowledge.get(agent_id, {}), t)
            if w is None or k is None:
                continue
            correct, denom = _count_filtered_facts(k, w, domain.agent_ids, _ATTRS, fact_filter)
            if denom == 0:
                continue
            vals.append((t, correct / denom))
        result[agent_id] = vals
    return result


def compute_m2(
    world_states: dict[int, WorldSnapshot],
    knowledge: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
) -> dict[int, list[tuple[int, float]]]:
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id in domain.agent_ids:
        vals = []
        for t in timesteps:
            w = get_world_state_at(world_states, t)
            k = get_knowledge_at(knowledge.get(agent_id, {}), t)
            if w is None or k is None:
                continue
            correct, denom = _count_filtered_facts(k, w, domain.agent_ids, ['house', 'pet'], None)
            if denom == 0:
                continue
            vals.append((t, (denom - correct) / denom))
        result[agent_id] = vals
    return result


def compute_m4(
    world_states: dict[int, WorldSnapshot],
    knowledge: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
    horizon: int = 1,
    fact_filter: Optional[FactFilter] = None,
) -> dict[int, list[tuple[int, float]]]:
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id in domain.agent_ids:
        vals = []
        for t in timesteps:
            k = get_knowledge_at(knowledge.get(agent_id, {}), t)
            w_fut = get_world_state_at(world_states, t + horizon)
            if k is None or w_fut is None:
                continue
            preds = [
                (aid, s.location) for aid, s in k.known_agents.items()
                if aid != agent_id
                and s.location != -1
                and (fact_filter is None or fact_filter.matches(aid, 'location', s.location))
            ]
            if not preds:
                continue
            correct = sum(
                1 for aid, loc in preds
                if w_fut.agents.get(aid) and w_fut.agents[aid].location == loc
            )
            vals.append((t, correct / len(preds)))
        result[agent_id] = vals
    return result


def compute_m8(
    k_fol_series: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
) -> dict[int, list[tuple[int, float]]]:
    from .log_parser import get_knowledge_at
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id, series in k_fol_series.items():
        vals = []
        for t in timesteps:
            k = get_knowledge_at(series, t)
            if k is None:
                continue
            n = len(k.known_agents)
            vals.append((t, len(k.inferred_agent_ids) / n if n > 0 else 0.0))
        result[agent_id] = vals
    return result


def _build_agent_event_index(
    events: list[dict],
) -> dict[int, list[tuple[int, str]]]:
    index: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for e in events:
        et = e['event_type']
        t = e['time']
        et_low = et.lower()
        if et_low in ('starttrip', 'finishtrip'):
            aid = e.get('agent_id', -1)
            if aid >= 0:
                index[aid].append((t, et_low))
        elif et_low in ('changehouse', 'changepet'):
            for aid, _ in e.get('participants', []):
                if aid >= 0:
                    index[aid].append((t, et_low))
    for aid in index:
        index[aid].sort()
    return index


def _fact_horizon(
    agent_id: int,
    attribute: str,
    t: int,
    event_index: dict[int, list[tuple[int, str]]],
    max_horizon: int,
) -> int:
    invalidating = {'location': {'starttrip', 'finishtrip'},
                    'house': {'changehouse'},
                    'pet': {'changepet'}}
    relevant = invalidating.get(attribute, set())
    events_for_agent = event_index.get(agent_id, [])
    times = [ev[0] for ev in events_for_agent]
    pos = bisect.bisect_left(times, t)
    for i in range(pos, len(events_for_agent)):
        ev_t, ev_type = events_for_agent[i]
        if ev_t - t > max_horizon:
            break
        if ev_type in relevant:
            return ev_t - t
    return max_horizon


def compute_m3(
    m1_series: dict[int, list[tuple[int, float]]],
    threshold: float = 0.5,
) -> dict[int, Optional[int]]:
    result: dict[int, Optional[int]] = {}
    for agent_id, vals in m1_series.items():
        result[agent_id] = next((t for t, v in vals if v >= threshold), None)
    return result


def compute_m9(
    world_states: dict[int, WorldSnapshot],
    k_raw_series: dict[int, dict[int, KnowledgeSnapshot]],
    k_fol_series: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
    fact_filter: Optional[FactFilter] = None,
) -> dict[int, list[tuple[int, float]]]:
    m1_raw = compute_m1(world_states, k_raw_series, timesteps, domain, fact_filter)
    m1_fol = compute_m1(world_states, k_fol_series, timesteps, domain, fact_filter)
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id in domain.agent_ids:
        raw_map = dict(m1_raw.get(agent_id, []))
        fol_map = dict(m1_fol.get(agent_id, []))
        vals = sorted((t, fol_map[t] - raw_map[t]) for t in fol_map if t in raw_map)
        result[agent_id] = vals
    return result


def _drop_snapshots(
    series: dict[int, KnowledgeSnapshot],
    p: float,
    rng: random.Random,
) -> _TimestampedDict:
    droppable = [t for t in series if t != 0]
    n_drop = int(len(droppable) * p)
    to_drop = set(rng.sample(droppable, min(n_drop, len(droppable))))
    return _TimestampedDict({t: snap for t, snap in series.items() if t not in to_drop})


def _enrich_series(
    series: dict[int, KnowledgeSnapshot],
    domain: Domain,
) -> dict[int, KnowledgeSnapshot]:
    from .z3_solver import infer_knowledge
    return {t: infer_knowledge(snap, domain) for t, snap in series.items()}


def _mean_series(vals: list[tuple[int, float]]) -> float:
    return sum(v for _, v in vals) / len(vals) if vals else 0.0


def compute_m5(
    world_states: dict[int, WorldSnapshot],
    k_raw_series: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
    drop_rates: Sequence[float] = (0.0, 0.1, 0.2, 0.3, 0.5),
    n_trials: int = 10,
    seed: int = 42,
    apply_fol: bool = False,
) -> dict[int, dict[float, float]]:
    result: dict[int, dict[float, float]] = {}
    for agent_id in domain.agent_ids:
        full_raw = k_raw_series.get(agent_id, {})
        working = _enrich_series(full_raw, domain) if apply_fol else full_raw
        baseline_mean = _mean_series(
            compute_m1(world_states, {agent_id: working}, timesteps, domain).get(agent_id, [])
        )
        ratios: dict[float, float] = {}
        for p in drop_rates:
            trial_ratios = []
            for trial in range(n_trials):
                rng = random.Random(seed + trial)
                dropped = _drop_snapshots(working, p, rng)
                dropped_mean = _mean_series(
                    compute_m1(world_states, {agent_id: dropped}, timesteps, domain).get(agent_id, [])
                )
                trial_ratios.append(dropped_mean / baseline_mean if baseline_mean > 0 else 1.0)
            ratios[p] = sum(trial_ratios) / n_trials
        result[agent_id] = ratios
    return result


def compute_m6(
    events: list[dict],
    world_states: dict[int, WorldSnapshot],
    knowledge: dict[int, dict[int, KnowledgeSnapshot]],
    timesteps: list[int],
    domain: Domain,
    fact_filter: Optional[FactFilter] = None,
    max_horizon: int = 100,
) -> dict[int, list[tuple[int, float]]]:
    event_index = _build_agent_event_index(events)
    result: dict[int, list[tuple[int, float]]] = {}
    for agent_id in domain.agent_ids:
        vals = []
        for t in timesteps:
            k = get_knowledge_at(knowledge.get(agent_id, {}), t)
            if k is None or not k.known_agents:
                continue
            horizons = []
            for aid, s in k.known_agents.items():
                for attr in _ATTRS:
                    val = getattr(s, attr)
                    if fact_filter is not None and not fact_filter.matches(aid, attr, val):
                        continue
                    horizons.append(_fact_horizon(aid, attr, t, event_index, max_horizon))
            if not horizons:
                continue
            vals.append((t, sum(horizons) / len(horizons) / max_horizon))
        result[agent_id] = vals
    return result
