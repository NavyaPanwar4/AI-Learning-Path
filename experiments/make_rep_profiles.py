"""Write the replication profile set (new seed, more profiles, two learner models).

  python -m experiments.make_rep_profiles            # -> experiments/data/profiles_rep.json
Then (per model):
  python -m experiments.run --provider groq --model openai/gpt-oss-120b --split rep \
         --profiles-file experiments/data/profiles_rep.json
"""
import os

from experiments.graphs import DATA_DIR, load_graph_p
from experiments.profiles import generate_replication_profiles, save_profiles


def main():
    graph, raw = load_graph_p()
    tracks = {n["id"]: n["track"] for n in raw["nodes"]}
    profiles = generate_replication_profiles(graph, tracks)
    out = os.path.join(DATA_DIR, "profiles_rep.json")
    save_profiles(profiles, out)
    print(f"Wrote {len(profiles)} profiles to {out}")


if __name__ == "__main__":
    main()
