from z3 import Distinct, Int, Or, Solver, sat, unsat

from .log_parser import Domain
from .world_state import AgentState, KnowledgeSnapshot


def _build_solver(k_raw: KnowledgeSnapshot, domain: Domain) -> tuple[Solver, dict, dict, dict, dict]:
    agent_ids = domain.agent_ids
    pet_to_int = {p: i for i, p in enumerate(domain.pets)}
    int_to_pet = {i: p for p, i in pet_to_int.items()}
    h_vars = {aid: Int(f'h_{aid}') for aid in agent_ids}
    p_vars = {aid: Int(f'p_{aid}') for aid in agent_ids}

    s = Solver()
    s.add(Distinct([h_vars[aid] for aid in agent_ids]))
    s.add(Distinct([p_vars[aid] for aid in agent_ids]))
    for aid in agent_ids:
        s.add(Or([h_vars[aid] == h for h in domain.houses]))
        s.add(Or([p_vars[aid] == i for i in range(len(domain.pets))]))
    for aid, state in k_raw.known_agents.items():
        s.add(h_vars[aid] == state.house)
        if state.pet in pet_to_int:
            s.add(p_vars[aid] == pet_to_int[state.pet])

    return s, h_vars, p_vars, pet_to_int, int_to_pet


def _check_forced(solver: Solver, var) -> int | None:
    proposed = solver.model().eval(var, model_completion=True).as_long()
    solver.push()
    solver.add(var != proposed)
    forced = solver.check() == unsat
    solver.pop()
    return proposed if forced else None


def _infer_unknown_agents(
    solver: Solver,
    h_vars: dict,
    p_vars: dict,
    int_to_pet: dict,
    unknown_ids: list[int],
    t: int,
) -> dict[int, AgentState]:
    inferred: dict[int, AgentState] = {}
    for aid in unknown_ids:
        forced_house = _check_forced(solver, h_vars[aid])
        forced_pet_int = _check_forced(solver, p_vars[aid])
        forced_pet = int_to_pet.get(forced_pet_int) if forced_pet_int is not None else None
        if forced_house is not None or forced_pet is not None:
            inferred[aid] = AgentState(
                agent_id=aid,
                house=forced_house if forced_house is not None else -1,
                pet=forced_pet if forced_pet is not None else '',
                location=-1,
                t=t,
            )
    return inferred


def infer_knowledge(k_raw: KnowledgeSnapshot, domain: Domain) -> KnowledgeSnapshot:
    solver, h_vars, p_vars, _, int_to_pet = _build_solver(k_raw, domain)
    if solver.check() != sat:
        return k_raw

    unknown_ids = [aid for aid in domain.agent_ids if aid not in k_raw.known_agents]
    if not unknown_ids:
        return k_raw

    inferred = _infer_unknown_agents(solver, h_vars, p_vars, int_to_pet, unknown_ids, k_raw.t)
    if not inferred:
        return k_raw

    return KnowledgeSnapshot(
        observer_id=k_raw.observer_id,
        t=k_raw.t,
        known_agents={**k_raw.known_agents, **inferred},
        inferred_agent_ids=set(inferred.keys()),
    )
