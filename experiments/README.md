# Experiments: LLM-only vs. prerequisite-aware, rule-based planning

Harness for the study described in the paper. **Nothing here has been run against a real LLM.**
All numbers appear only after you run the steps below. Run commands from the repository root.

## What is compared

| ID | Condition | How the path is made |
|----|-----------|----------------------|
| A | LLM-only | LLM gets goal targets, mastery table, skill catalogue and general personalisation instructions |
| E | LLM + structure as text | A, plus the prerequisite edges and the exact rules as prompt text; nothing is enforced |
| D | Proposed system | `app/services/path_planner.py` picks skills/order/actions (enforced); LLM only elaborates titles |
| B | Planner, graph only | planner with mastery ignored (deterministic, no LLM) |
| C | Mastery only | A's skill list filtered by the mastery rules, no graph (derived from A, no extra LLM call) |

Primary contrasts (confirmatory): **A vs D** and **E vs D** on **PVR** (prerequisite violation rate) and
**MA** (mastery alignment), Holm-corrected over those 4 tests. Everything else is exploratory.
Metric definitions are in `experiments/metrics.py` (docstrings) and the paper's Section 5.5.

## Before any real run (human steps)

1. **Review `data/graph_P.json`.** It is a DRAFT (40 skills, 43 edges) written by Claude from your skill
   catalogue. Edit it until you agree with every edge. Also review `data/goals.json` (3 goals).
2. **Independent graph E.** Give a second person ONLY the files from
   `python -c "from experiments.graphs import *; g,raw=load_graph_p(); write_graph_e_template(g, raw['nodes'], 'graph_E_package')"`
   (skills list + instructions). They must work blind. Put their result at
   `experiments/data/graph_E_edges.csv`. Until it exists, analysis scores against graph P and labels
   PVR/OC as NOT INDEPENDENT (circular).
3. **Freeze.** Commit graph P, goals, profiles, prompts (`conditions.py`), planner, metrics and
   `config.json`, tag the commit, and write down the analysis plan (see below) BEFORE touching the test split.
4. Set `GROQ_API_KEY` in `.env`; `openai/gpt-oss-120b` is the experiment harness's default model.

## Run

```bash
# pipeline smoke test, no LLM (results are flagged mock and refused by analyze.py)
python -m experiments.run --provider mock --split dev --out /tmp/mock_res

# 1) DEV pilot: tune prompts/rules ONLY on dev profiles, check floor/ceiling effects
python -m experiments.run --provider groq --split dev
python -m experiments.analyze --logs experiments/results/groq__openai-gpt-oss-120b__dev.jsonl \
       --out experiments/results/analysis_dev --split dev

# 2) after freezing: TEST split
python -m experiments.run --provider groq --split test
python -m experiments.analyze --logs experiments/results/groq__openai-gpt-oss-120b__test.jsonl \
       --out experiments/results/analysis_gpt-oss-120b --split test

# 3) human evaluation (blinded)
python -m experiments.human_eval export --logs experiments/results/groq__openai-gpt-oss-120b__test.jsonl \
       --out experiments/human_eval/round1
#    give blinded_items.md + rating_template.csv to 2-3 raters; keep key.json private
python -m experiments.human_eval analyze --dir experiments/human_eval/round1 --ratings r1.csv r2.csv r3.csv
```

Runs are resumable (existing keys in the JSONL are skipped). Every record stores the raw LLM output, seed,
prompt hash and latency; `*.meta.json` stores the config, git commit and graph/profile hashes.
`generate_experiment_json` is strict: no repair prompt or Hugging Face fallback (a failed parse is re-sampled
once with a new seed, and parse failures are reported). Groq is called with JSON-object mode,
temperature 0.1 and a per-call seed; `config.json` holds the experiment settings.

Rough size: per split = profiles x 3 goals x (3 A + 3 E + 1 D) LLM calls (test: 18 x 3 x 7 = 378 calls;
dev: 189). Time and rate limits depend on your Groq account: measure it on a few dev profiles with
`--profile-ids beg01,int01 --runs 1` first.

## Outputs (in the `--out` directory)

`summary_by_condition.csv`, `paired_tests.csv` (effect sizes, bootstrap CIs, Holm-adjusted p for the
confirmatory family), `friedman.csv`, `by_archetype.csv`, `profile_sensitivity.csv`,
`run_consistency.csv`, `generation_reliability.csv`, `floor_ceiling.csv`, `scored_runs.csv`,
`analysis_meta.json` (scoring graph, thresholds, graph agreement P vs E).
Threshold sensitivity: re-run `analyze` with `--weak 0.4 --strong 0.8` etc. (no regeneration needed).

## Design notes you should know

* Unit of analysis is the **profile** (metrics averaged over goals and runs). Runs of one profile are not independent.
* D's structure is deterministic, so its run-to-run consistency is trivially 1; one LLM elaboration per unit is made
  (`d_llm_runs`) to measure how well the LLM keeps to the plan (`adherence` in the log).
* Empty-plan profiles (e.g. advanced learners on the Data Analyst goal) are valid: an empty path is ideal there.
  Metrics with an empty denominator are undefined (NaN) and excluded; counts are in `summary_by_condition.csv`.
* Profile sensitivity is undefined when all paths are identical (a learner-independent path).
* Mastery values are synthetic (`profiles.py`). They test alignment with a given mastery state, NOT learning gains.
* The closed loop (quiz -> mastery update -> re-plan) is not evaluated here.

## Tests

`python -m pytest tests` (hand-computed metric checks, planner, statistics, and a mock end-to-end pipeline).
