import ast
import bisect
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .world_state import AgentState, KnowledgeSnapshot, WorldSnapshot

_warned_nationalities: set[str] = set()


class _TimestampedDict(dict):
    __slots__ = ('_sorted_keys',)

    def __init__(self, data):
        super().__init__(data)
        self._sorted_keys: list[int] = sorted(self)


def _cached_sorted_keys(d: dict) -> list[int]:
    sk = getattr(d, '_sorted_keys', None)
    return sk if sk is not None else sorted(d)


def _resolve_nat(domain: 'Domain', nat: str) -> int:
    aid = domain.nationality_to_id.get(nat, -1)
    if aid == -1 and nat not in _warned_nationalities:
        print(f"[fol_parser] warning: unknown nationality '{nat}', mapped to -1", file=sys.stderr)
        _warned_nationalities.add(nat)
    return aid


@dataclass
class Domain:
    agent_ids: list[int]
    nationality_to_id: dict[str, int]
    pets: list[str]
    houses: list[int]
    initial_state: dict[int, AgentState]


def load_domain(zebra_csv_path: str) -> Domain:
    agent_ids, nationality_to_id, pets, houses = [], {}, [], []
    initial_state: dict[int, AgentState] = {}
    with open(zebra_csv_path, encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split(';')
            if len(parts) < 6:
                continue
            aid = int(parts[0])
            nat, pet = parts[2], parts[5]
            agent_ids.append(aid)
            nationality_to_id[nat] = aid
            pets.append(pet)
            houses.append(aid)
            initial_state[aid] = AgentState(aid, aid, pet, aid, 0)
    return Domain(agent_ids, nationality_to_id, pets, houses, initial_state)


def _parse_start_trip(parts: list[str], domain: Domain) -> dict:
    nat = parts[3]
    return {
        'event_type': 'StartTrip',
        'agent_id': _resolve_nat(domain, nat),
        'from_house': int(parts[4]),
        'to_house': int(parts[5]),
    }


def _parse_finish_trip(parts: list[str], domain: Domain) -> dict:
    if len(parts) == 5:
        nat, house = parts[3], int(parts[4])
        result = 1
    else:
        result, nat, house = int(parts[3]), parts[4], int(parts[5])
    return {
        'event_type': 'FinishTrip',
        'result': result,
        'agent_id': _resolve_nat(domain, nat),
        'house': house,
    }


def _parse_exchange(parts: list[str], event_type: str, domain: Domain) -> dict:
    n = int(parts[3])
    nats = parts[4:4 + n]
    vals = parts[4 + n:4 + 2 * n]
    is_house = event_type.lower() == 'changehouse'
    participants = [
        (_resolve_nat(domain, nat), int(v) if is_house else v)
        for nat, v in zip(nats, vals)
    ]
    return {'event_type': event_type, 'participants': participants}


def parse_observer_csv(path: str, domain: Domain) -> list[dict]:
    events = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('----'):
                break
            parts = line.split(';')
            if len(parts) < 3:
                continue
            try:
                event_num, time = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            et, base = parts[2], {'event_num': event_num, 'time': time}
            et_low = et.lower()
            try:
                if et_low == 'starttrip':
                    base.update(_parse_start_trip(parts, domain))
                elif et_low == 'finishtrip':
                    base.update(_parse_finish_trip(parts, domain))
                elif et_low in ('changehouse', 'changepet'):
                    base.update(_parse_exchange(parts, et, domain))
                else:
                    print(f"[fol_parser] warning: unknown event type '{et}' at t={time}, skipped",
                          file=sys.stderr)
                    continue
            except (IndexError, ValueError) as exc:
                print(f"[fol_parser] warning: malformed line skipped (t={time}, type={et}): {exc}",
                      file=sys.stderr)
                continue
            events.append(base)
    return events


def _copy_agents(agents: dict[int, AgentState]) -> dict[int, AgentState]:
    return {aid: AgentState(s.agent_id, s.house, s.pet, s.location, s.t)
            for aid, s in agents.items()}


def _apply_event(event: dict, current: dict[int, AgentState], t: int) -> None:
    et = event['event_type'].lower()
    if et == 'starttrip':
        aid = event['agent_id']
        s = current[aid]
        current[aid] = AgentState(aid, s.house, s.pet, -1, t)
    elif et == 'finishtrip':
        aid = event['agent_id']
        s = current[aid]
        current[aid] = AgentState(aid, s.house, s.pet, event['house'], t)
    elif et == 'changehouse':
        for aid, new_house in event['participants']:
            s = current[aid]
            current[aid] = AgentState(aid, new_house, s.pet, s.location, t)
    elif et == 'changepet':
        for aid, new_pet in event['participants']:
            s = current[aid]
            current[aid] = AgentState(aid, s.house, new_pet, s.location, t)


_PRIORITY = {'finishtrip': 0, 'changehouse': 1, 'changepet': 1, 'starttrip': 2}


def reconstruct_world_states(
    events: list[dict],
    domain: Domain,
) -> dict[int, WorldSnapshot]:
    current = {aid: AgentState(aid, s.house, s.pet, s.location, 0)
               for aid, s in domain.initial_state.items()}
    world_states: dict[int, WorldSnapshot] = {0: WorldSnapshot(0, _copy_agents(current))}
    events_by_time: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        events_by_time[e['time']].append(e)
    prev = {aid: (s.house, s.pet, s.location) for aid, s in current.items()}
    for t in sorted(events_by_time):
        batch = events_by_time[t]
        phase_a = [e for e in batch if e['event_type'].lower() != 'starttrip']
        phase_a.sort(key=lambda e: _PRIORITY.get(e['event_type'].lower(), 1))
        for event in phase_a:
            _apply_event(event, current, t)
        new = {aid: (s.house, s.pet, s.location) for aid, s in current.items()}
        if new != prev:
            world_states[t] = WorldSnapshot(t, _copy_agents(current))
            prev = new
        phase_b = [e for e in batch if e['event_type'].lower() == 'starttrip']
        for event in phase_b:
            _apply_event(event, current, t)
        after_b = {aid: (s.house, s.pet, s.location) for aid, s in current.items()}
        if after_b != prev:
            world_states[t] = WorldSnapshot(t, _copy_agents(current))
        prev = after_b
    return _TimestampedDict(world_states)


def get_world_state_at(
    world_states: dict[int, WorldSnapshot],
    t: int,
) -> Optional[WorldSnapshot]:
    if not world_states:
        return None
    if t in world_states:
        return world_states[t]
    keys = _cached_sorted_keys(world_states)
    idx = bisect.bisect_right(keys, t) - 1
    return world_states[keys[idx]] if idx >= 0 else None


def _parse_knowledge_line(line: str, agent_id: int) -> Optional[tuple[int, KnowledgeSnapshot]]:
    parts = line.split(';', 2)
    if len(parts) < 3:
        return None
    try:
        t = int(parts[0])
        raw = ast.literal_eval(parts[2])
    except (ValueError, SyntaxError):
        return None
    known: dict[int, AgentState] = {}
    for aid, info in raw.items():
        aid = int(aid)
        known[aid] = AgentState(aid, int(info['house']), str(info['pet']),
                                int(info['location']), int(info['t']))
    return t, KnowledgeSnapshot(agent_id, t, known, set())


def parse_agent_knowledge_log(path: str, agent_id: int) -> _TimestampedDict:
    snapshots: dict[int, KnowledgeSnapshot] = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('----'):
                break
            result = _parse_knowledge_line(line, agent_id)
            if result is not None:
                t, snap = result
                snapshots[t] = snap
    return _TimestampedDict(snapshots)


def load_all_knowledge(
    logs_dir: str,
    agent_ids: list[int],
) -> dict[int, dict[int, KnowledgeSnapshot]]:
    result: dict[int, dict[int, KnowledgeSnapshot]] = {}
    for aid in agent_ids:
        path = os.path.join(logs_dir, f'agent_{aid}_knowledge.log')
        if os.path.exists(path):
            result[aid] = parse_agent_knowledge_log(path, aid)
    return result


def get_knowledge_at(
    knowledge_series: dict[int, KnowledgeSnapshot],
    t: int,
) -> Optional[KnowledgeSnapshot]:
    if not knowledge_series:
        return None
    if t in knowledge_series:
        return knowledge_series[t]
    keys = _cached_sorted_keys(knowledge_series)
    idx = bisect.bisect_right(keys, t) - 1
    return knowledge_series[keys[idx]] if idx >= 0 else None
