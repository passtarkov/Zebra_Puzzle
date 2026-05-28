import os

from .fact_filter import FactFilter
from .loader import MetricsBundle, load_metrics, compute_filtered_metrics
from .log_parser import (
    Domain,
    get_knowledge_at,
    load_all_knowledge,
    load_domain,
    parse_observer_csv,
    reconstruct_world_states,
)
from .metrics import compute_m1, compute_m2, compute_m3, compute_m4, compute_m5, compute_m6, compute_m8, compute_m9
from .world_state import KnowledgeSnapshot
from .z3_solver import infer_knowledge


def _save_metric_csv(path: str, metric: dict[int, list[tuple[int, float]]]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write('agent_id;t;value\n')
        for agent_id in sorted(metric):
            for t, v in metric[agent_id]:
                f.write(f'{agent_id};{t};{v:.6f}\n')


def _save_m5_csv(path: str, m5: dict[int, dict[float, float]]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write('agent_id;drop_rate;robustness_ratio\n')
        for agent_id in sorted(m5):
            for drop_rate in sorted(m5[agent_id]):
                f.write(f'{agent_id};{drop_rate};{m5[agent_id][drop_rate]:.6f}\n')


def _save_m3_csv(path: str, m3: dict[int, int | None], threshold: float) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        f.write('agent_id;threshold;t_reached\n')
        for agent_id in sorted(m3):
            t_reached = m3[agent_id]
            f.write(f'{agent_id};{threshold};{t_reached if t_reached is not None else ""}\n')


def _build_k_fol(
    k_raw: dict[int, dict[int, KnowledgeSnapshot]],
    domain: Domain,
    timesteps: list[int],
) -> tuple[dict[int, dict[int, KnowledgeSnapshot]], dict[int, dict[int, KnowledgeSnapshot]]]:
    infer_cache: dict[tuple[int, int], KnowledgeSnapshot] = {}
    k_fol: dict[int, dict[int, KnowledgeSnapshot]] = {aid: {} for aid in domain.agent_ids}
    for agent_id in domain.agent_ids:
        series = k_raw.get(agent_id, {})
        for t in timesteps:
            raw = get_knowledge_at(series, t)
            if raw is None:
                continue
            cache_key = (raw.observer_id, raw.t)
            if cache_key not in infer_cache:
                infer_cache[cache_key] = infer_knowledge(raw, domain)
            k_fol[agent_id][t] = infer_cache[cache_key]

    k_enriched: dict[int, dict[int, KnowledgeSnapshot]] = {}
    for agent_id in domain.agent_ids:
        series = k_raw.get(agent_id, {})
        k_enriched[agent_id] = {}
        for snap_t, raw in series.items():
            cache_key = (raw.observer_id, raw.t)
            k_enriched[agent_id][snap_t] = (
                infer_cache[cache_key] if cache_key in infer_cache
                else infer_knowledge(raw, domain)
            )

    return k_fol, k_enriched


def run_fol_analysis(
    observer_csv: str,
    logs_dir: str,
    zebra_csv: str,
    output_dir: str,
    timestep_resolution: int = 1,
    horizon_cap: int = 100,
    m3_threshold: float = 0.5,
    m5_drop_rates: list[float] = (0.0, 0.1, 0.2, 0.3, 0.5),
    m5_n_trials: int = 10,
    m5_seed: int = 42,
) -> dict:
    domain = load_domain(zebra_csv)
    events = parse_observer_csv(observer_csv, domain)
    world_states = reconstruct_world_states(events, domain)
    k_raw = load_all_knowledge(logs_dir, domain.agent_ids)

    k_raw_times = {t for series in k_raw.values() for t in series}
    all_times = sorted(set(world_states.keys()) | k_raw_times)
    if not all_times:
        timesteps = []
    else:
        t_min, t_max = all_times[0], all_times[-1]
        timesteps = list(range(t_min, t_max + 1, timestep_resolution))
    k_fol, k_enriched = _build_k_fol(k_raw, domain, timesteps)

    m1 = compute_m1(world_states, k_fol, timesteps, domain)
    m1_raw = compute_m1(world_states, k_raw, timesteps, domain)
    m2 = compute_m2(world_states, k_fol, timesteps, domain)
    m3 = compute_m3(m1, threshold=m3_threshold)
    m4 = compute_m4(world_states, k_fol, timesteps, domain)
    m6 = compute_m6(events, world_states, k_fol, timesteps, domain, max_horizon=horizon_cap)
    m8 = compute_m8(k_fol, timesteps)
    m9 = compute_m9(world_states, k_raw, k_fol, timesteps, domain)
    m5_raw = compute_m5(world_states, k_raw, timesteps, domain,
                        drop_rates=m5_drop_rates, n_trials=m5_n_trials,
                        seed=m5_seed, apply_fol=False)
    m5_fol = compute_m5(world_states, k_enriched, timesteps, domain,
                        drop_rates=m5_drop_rates, n_trials=m5_n_trials,
                        seed=m5_seed, apply_fol=False)

    os.makedirs(output_dir, exist_ok=True)
    for name, metric in [('m1', m1), ('m1_raw', m1_raw), ('m2', m2), ('m4', m4),
                          ('m6', m6), ('m8', m8), ('m9', m9)]:
        _save_metric_csv(os.path.join(output_dir, f'{name}.csv'), metric)
    _save_m3_csv(os.path.join(output_dir, 'm3.csv'), m3, m3_threshold)
    _save_m5_csv(os.path.join(output_dir, 'm5_raw.csv'), m5_raw)
    _save_m5_csv(os.path.join(output_dir, 'm5_fol.csv'), m5_fol)

    return {'m1': m1, 'm1_raw': m1_raw, 'm2': m2, 'm3': m3, 'm4': m4,
            'm6': m6, 'm8': m8, 'm9': m9, 'm5_raw': m5_raw, 'm5_fol': m5_fol}
