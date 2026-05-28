from dataclasses import dataclass


@dataclass
class FactFilter:
    agent_id: int | None = None
    attribute: str | None = None
    value: object | None = None

    def matches(self, agent_id: int, attribute: str, value) -> bool:
        if self.agent_id is not None and agent_id != self.agent_id:
            return False
        if self.attribute is not None and attribute != self.attribute:
            return False
        if self.value is not None and value != self.value:
            return False
        return True
