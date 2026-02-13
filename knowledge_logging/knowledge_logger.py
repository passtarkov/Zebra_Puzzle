import os
import csv
from collections import defaultdict
from typing import Dict, List, Any, Optional


class KnowledgeLogAnalyzer:

    def __init__(
        self,
        observer_log_path: str,
        agents_csv_path: str,
        output_dir: str = "data/output_data/logs"
    ):
        self.observer_log_path = observer_log_path
        self.agents_csv_path = agents_csv_path
        self.output_dir = output_dir

        os.makedirs(self.output_dir, exist_ok=True)

        self.agents_metadata = self._load_agents_metadata()

        self.nationality_to_id = {
            meta["nationality"].strip().lower(): agent_id
            for agent_id, meta in self.agents_metadata.items()
        }

        self.agents_knowledge: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self.houses: Dict[int, Dict[str, Any]] = {}
        self.previous_knowledge_states: Dict[int, Dict[int, Dict[str, Any]]] = {}

        self._initialize_environment_state()
        self.events_by_time = self._parse_observer_log()

    def _load_agents_metadata(self) -> Dict[int, Dict[str, str]]:
        metadata = {}
        with open(self.agents_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            for row in reader:
                if len(row) < 6:
                    continue
                agent_id = int(row[0])
                metadata[agent_id] = {
                    'color': row[1],
                    'nationality': row[2],
                    'drink': row[3],
                    'cigarettes': row[4],
                    'pet': row[5]
                }
        return metadata

    def _initialize_environment_state(self) -> None:
        for agent_id, meta in self.agents_metadata.items():
            self.houses[agent_id] = {
                "owner_id": agent_id,
                "present_agents": {agent_id}
            }

            self.agents_knowledge[agent_id] = {
                agent_id: {
                    "pet": meta["pet"],
                    "house": agent_id,
                    "location": agent_id,
                    "t": 0
                }
            }

            self.previous_knowledge_states[agent_id] = {}

    def _parse_observer_log(self) -> Dict[int, List[Dict[str, Any]]]:
        events_by_time = defaultdict(list)

        with open(self.observer_log_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f, delimiter=';')
            next(reader, None)

            for row in reader:
                if not row or len(row) < 3:
                    continue

                try:
                    event_num = int(row[0])
                    time = int(row[1])
                    event_type = row[2].strip()
                except ValueError:
                    continue

                event = {
                    "event_num": event_num,
                    "time": time,
                    "event_type": event_type
                }

                if event_type == "FinishTrip":
                    if len(row) >= 6:
                        event.update({
                            "success": int(row[3]),
                            "nationality": row[4],
                            "house_id": int(row[5])
                        })
                    elif len(row) >= 5:
                        event.update({
                            "success": 1,
                            "nationality": row[3],
                            "house_id": int(row[4])
                        })

                elif event_type in ["changeHouse", "ChangePet"]:
                    if len(row) >= 4:
                        qty = int(row[3])
                        event["qty_participants"] = qty
                        event["nationalities"] = row[4:4 + qty]
                        rest = row[4 + qty:4 + qty + qty]

                        if event_type == "changeHouse":
                            event["houses_after"] = [int(x) for x in rest]
                        else:
                            event["pets_after"] = rest

                events_by_time[time].append(event)

        return events_by_time

    def _get_agent_id_by_nationality(self, nationality: str) -> Optional[int]:
        return self.nationality_to_id.get(nationality.strip().lower())

    def _exchange_knowledge(self, a1: int, a2: int, time: int) -> None:
        self.agents_knowledge[a1][a2] = {
            "pet": self.agents_knowledge[a2][a2]["pet"],
            "house": self.agents_knowledge[a2][a2]["house"],
            "location": self.agents_knowledge[a2][a2]["location"],
            "t": time
        }

        self.agents_knowledge[a2][a1] = {
            "pet": self.agents_knowledge[a1][a1]["pet"],
            "house": self.agents_knowledge[a1][a1]["house"],
            "location": self.agents_knowledge[a1][a1]["location"],
            "t": time
        }

    def _process_finish_trips(self, events: List[Dict[str, Any]], time: int) -> None:
        for event in sorted(events, key=lambda e: e["event_num"]):
            agent_id = self._get_agent_id_by_nationality(event["nationality"])
            if not agent_id:
                continue

            target_house = event["house_id"]
            success = event.get("success", 1)

            old_house = self.agents_knowledge[agent_id][agent_id]["location"]
            self.houses[old_house]["present_agents"].discard(agent_id)

            self.houses[target_house]["present_agents"].add(agent_id)

            self.agents_knowledge[agent_id][agent_id]["location"] = target_house
            self.agents_knowledge[agent_id][agent_id]["t"] = time

            if success == 1:
                present = list(self.houses[target_house]["present_agents"])
                for i, a1 in enumerate(present):
                    for a2 in present[i + 1:]:
                        self._exchange_knowledge(a1, a2, time)

    def _process_house_exchange(self, event: Dict[str, Any], time: int) -> None:
        participants = [
            self._get_agent_id_by_nationality(n)
            for n in event["nationalities"]
        ]

        houses_after = event.get("houses_after", [])

        if not participants or len(participants) != len(houses_after):
            return

        event_locations = set(
            self.agents_knowledge[agent_id][agent_id]["location"]
            for agent_id in participants
        )

        for i, agent_id in enumerate(participants):
            self.agents_knowledge[agent_id][agent_id]["house"] = houses_after[i]
            self.agents_knowledge[agent_id][agent_id]["t"] = time

        for i, agent_id in enumerate(participants):
            new_house = houses_after[i]
            self.houses[new_house]["owner_id"] = agent_id

        observers = set()
        for house_id in event_locations:
            observers.update(self.houses[house_id]["present_agents"])

        for observer in observers:
            for i, participant in enumerate(participants):
                if participant in self.agents_knowledge[observer]:
                    self.agents_knowledge[observer][participant]["house"] = houses_after[i]
                    self.agents_knowledge[observer][participant]["t"] = time

    def _process_pet_exchange(self, event: Dict[str, Any], time: int) -> None:
        participants = [
            self._get_agent_id_by_nationality(n)
            for n in event["nationalities"]
        ]

        pets_after = event.get("pets_after", [])

        if not participants or len(participants) != len(pets_after):
            return

        event_locations = set(
            self.agents_knowledge[agent_id][agent_id]["location"]
            for agent_id in participants
        )

        for i, agent_id in enumerate(participants):
            self.agents_knowledge[agent_id][agent_id]["pet"] = pets_after[i]
            self.agents_knowledge[agent_id][agent_id]["t"] = time

        observers = set()
        for house_id in event_locations:
            observers.update(self.houses[house_id]["present_agents"])

        for observer in observers:
            for i, participant in enumerate(participants):
                if participant in self.agents_knowledge[observer]:
                    self.agents_knowledge[observer][participant]["pet"] = pets_after[i]
                    self.agents_knowledge[observer][participant]["t"] = time

    def _knowledge_changed(self, agent_id: int) -> bool:
        previous = self.previous_knowledge_states.get(agent_id, {})
        current = self.agents_knowledge[agent_id]

        if len(previous) != len(current):
            return True

        for other_id, info in current.items():
            if other_id not in previous:
                return True

            prev_info = previous[other_id]
            for field in ["pet", "house", "location"]:
                if info.get(field) != prev_info.get(field):
                    return True

        return False

    def _snapshot(self, agent_id: int) -> Dict:
        return {
            k: dict(v)
            for k, v in self.agents_knowledge[agent_id].items()
        }

    def _log_knowledge_state(self, time: int, event_type: str) -> None:
        for agent_id in self.agents_knowledge:
            if self._knowledge_changed(agent_id):
                filename = os.path.join(
                    self.output_dir,
                    f"agent_{agent_id}_knowledge.log"
                )

                with open(filename, "a", encoding="utf-8") as f:
                    f.write(
                        f"{time};{event_type};"
                        f"{self.agents_knowledge[agent_id]}\n"
                    )

                self.previous_knowledge_states[agent_id] = self._snapshot(agent_id)

    def generate_knowledge_logs(self) -> None:
        for agent_id in self.agents_knowledge:
            filename = os.path.join(
                self.output_dir,
                f"agent_{agent_id}_knowledge.log"
            )

            with open(filename, "w", encoding="utf-8") as f:
                f.write(
                    f"0;INIT;{self.agents_knowledge[agent_id]}\n"
                )

            self.previous_knowledge_states[agent_id] = self._snapshot(agent_id)

        for t in sorted(self.events_by_time.keys()):
            batch = self.events_by_time[t]

            finish = [e for e in batch if e["event_type"] == "FinishTrip"]
            house_ex = [e for e in batch if e["event_type"] == "changeHouse"]
            pet_ex = [e for e in batch if e["event_type"] == "ChangePet"]

            if finish:
                self._process_finish_trips(finish, t)
                self._log_knowledge_state(t, "FinishTrip")

            if house_ex:
                for e in sorted(house_ex, key=lambda x: x["event_num"]):
                    self._process_house_exchange(e, t)
                self._log_knowledge_state(t, "ChangeHouse")

            if pet_ex:
                for e in sorted(pet_ex, key=lambda x: x["event_num"]):
                    self._process_pet_exchange(e, t)
                self._log_knowledge_state(t, "ChangePet")

