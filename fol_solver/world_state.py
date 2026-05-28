from dataclasses import dataclass, field


@dataclass
class AgentState:
    agent_id: int
    house: int
    pet: str
    location: int
    t: int


@dataclass
class WorldSnapshot:
    t: int
    agents: dict[int, AgentState]


@dataclass
class KnowledgeSnapshot:
    observer_id: int
    t: int
    known_agents: dict[int, AgentState]
    inferred_agent_ids: set[int] = field(default_factory=set)
