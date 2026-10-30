"""Load/compare prerequisite graphs for the experiments (graph P and graph E)."""
from __future__ import annotations

import csv
import json
import os
from typing import Dict, List, Optional, Tuple

from app.services.path_planner import SkillGraph, SkillNode

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_graph_json(path: str) -> Tuple[SkillGraph, dict]:
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    nodes = [SkillNode(n["id"], n["name"], int(n.get("difficulty", 1)), float(n.get("hours", 1.0)))
             for n in raw["nodes"]]
    return SkillGraph(nodes, [tuple(e) for e in raw["edges"]]), raw


def load_graph_p(path: Optional[str] = None) -> Tuple[SkillGraph, dict]:
    return load_graph_json(path or os.path.join(DATA_DIR, "graph_P.json"))


def load_goals(path: Optional[str] = None) -> List[dict]:
    with open(path or os.path.join(DATA_DIR, "goals.json"), encoding="utf-8") as fh:
        return json.load(fh)["goals"]


def load_graph_e(nodes_from: SkillGraph, path: Optional[str] = None) -> Optional[SkillGraph]:
    """Graph E: independently authored edges in a CSV with columns
    ``prerequisite_id,skill_id``. Returns None if the file is absent or empty
    (the runner then falls back to graph P and flags results as NOT independent).
    Uses the node set (names/hours/difficulty) of graph P."""
    path = path or os.path.join(DATA_DIR, "graph_E_edges.csv")
    if not os.path.exists(path):
        return None
    edges = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            u, v = (row.get("prerequisite_id") or "").strip(), (row.get("skill_id") or "").strip()
            if u and v:
                edges.append((u, v))
    if not edges:
        return None
    return SkillGraph(list(nodes_from.nodes.values()), edges)


def ancestor_pairs(graph: SkillGraph) -> set:
    return {(a, s) for s in graph.nodes for a in graph.ancestors(s)}


def compare_graphs(a: SkillGraph, b: SkillGraph) -> Dict[str, float]:
    """Agreement between two graphs over the same nodes.

    * edge Jaccard on direct edges;
    * Cohen's kappa on the ancestor relation over all ordered node pairs
      (more forgiving than direct edges, because two authors may choose
      different but equivalent intermediate links).
    """
    ids = sorted(a.nodes)
    if sorted(b.nodes) != ids:
        raise ValueError("Graphs must have the same node ids")
    ea, eb = set(a.edges()), set(b.edges())
    jacc = len(ea & eb) / len(ea | eb) if (ea | eb) else 1.0
    pa, pb = ancestor_pairs(a), ancestor_pairs(b)
    n = len(ids) * (len(ids) - 1)
    both = len(pa & pb)
    only_a, only_b = len(pa - pb), len(pb - pa)
    neither = n - both - only_a - only_b
    po = (both + neither) / n
    pa1, pb1 = len(pa) / n, len(pb) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    kappa = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    return {
        "edges_a": len(ea), "edges_b": len(eb), "edge_jaccard": round(jacc, 4),
        "ancestor_pairs_a": len(pa), "ancestor_pairs_b": len(pb),
        "ancestor_agreement": round(po, 4), "ancestor_kappa": round(kappa, 4),
    }


def write_graph_e_template(graph: SkillGraph, raw_nodes: List[dict], out_dir: str) -> None:
    """Files handed to the independent second author (they must NOT see graph P)."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "graph_E_skills.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["skill_id", "skill_name", "difficulty", "estimated_hours"])
        for n in raw_nodes:
            w.writerow([n["id"], n["name"], n["difficulty"], n["hours"]])
    with open(os.path.join(out_dir, "graph_E_edges.csv"), "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["prerequisite_id", "skill_id"])
    with open(os.path.join(out_dir, "GRAPH_E_INSTRUCTIONS.txt"), "w", encoding="utf-8") as fh:
        fh.write(
            "Task: independently author a prerequisite graph for these skills.\n"
            "Add one row to graph_E_edges.csv for every DIRECT prerequisite relation\n"
            "(prerequisite_id -> skill_id) meaning: a typical learner should know the\n"
            "prerequisite before starting the skill.\n"
            "- Only direct prerequisites; omit relations implied by a chain (A->B->C: do not add A->C).\n"
            "- The graph must be acyclic.\n"
            "- Work alone and do not look at any existing graph, an LLM-made graph, or the project repository.\n"
            "- Use your own knowledge or textbooks and record the sources you used in a separate note.\n"
        )
