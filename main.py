import os

from analysis import SimulationAnalyzer
from fol_solver import run_fol_analysis
from knowledge_logging import KnowledgeLogAnalyzer
from loaders.csv_utils import load_strategies, load_initial_data, load_geography
from simulation.environment import Environment

 
if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    strategies = load_strategies(os.path.join(base_dir, "data/other_data/uniform_strategies.csv"))
    agents, houses = load_initial_data(os.path.join(base_dir, "data/input_data/zebra-01.csv"), strategies=strategies)
    T = load_geography(os.path.join(base_dir, "data/other_data/random_geo.csv"))

    max_time = 2000
    envi = Environment(agents, houses, T, max_time)
    log = envi.run(max_time)

    output_dir = os.path.join(base_dir, "data/output_data/logs")
    os.makedirs(output_dir, exist_ok=True)

    log_file_path = os.path.join(output_dir, "observer.csv")
    with open(log_file_path, "w", encoding="utf-8") as f:
        for entry in log:
            f.write(entry + "\n")
        f.write("---- KNOWLEDGE ----\n")
        for a in envi.agents.values():
            f.write(f"{a.id};{a.knowledge}\n")

    # Run log analysis
    analyzer = SimulationAnalyzer(log_file_path)
    analyzer.run_complete_analysis()

    knowledge = KnowledgeLogAnalyzer(
    observer_log_path="data/output_data/logs/observer.csv",
    agents_csv_path="data/input_data/zebra-01.csv",
    output_dir="data/output_data/logs/"
    )
    knowledge.generate_knowledge_logs()

    run_fol_analysis(
        observer_csv=log_file_path,
        logs_dir=output_dir,
        zebra_csv=os.path.join(base_dir, "data/input_data/zebra-01.csv"),
        output_dir=os.path.join(base_dir, "data/output_data/fol_metrics/"),
    )

