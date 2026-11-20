# Selective-SAST on Jamstack Architecture — Replication Package

Replication package (dataset, analysis scripts, and figures) for the study:

> **CI/CD Pipeline Execution Time Optimization Using Code Churn-Based Selective-SAST on Jamstack Architecture**  
> Fadilah Tun Hazimah, Muhammad Faisal, Emil Agusalim Habi Talib, and Titik Khawa Abd Rahman  
> *Journal of Informatics Unisla (JOUTICA)*, Vol. 11, No. 2, pp. 241–256, 2026.  
> DOI: [10.30736/jti.v11i2.1695](https://doi.org/10.30736/jti.v11i2.1695)

## Overview

This repository contains the empirical dataset and Python pipeline used to evaluate a **code churn-based Selective-SAST** prioritization strategy against a **Full-SAST** (Semgrep) baseline across **49 open-source Jamstack/SSG repositories** (**2,450 unique commits**, **120,472 file-commit observations**, and **105,933 cumulative raw Full-SAST findings**).

Files are prioritized for selective scanning when at least one of four risk predicates is met:
1. Relative code churn (30-day window) > 75th percentile (P75) within the repository.
2. Developer entropy (90-day window) > 1.5.
3. Modification intersects sensitive paths (Authentication, API, Configuration, or CI/CD).
4. Days since last modification > 14 days.

## Repository Structure

```text
.
├── data/
│   ├── interim/
│   │   ├── 01_repositories_metadata.parquet      # Initial candidate repositories from discovery
│   │   ├── 02_selected_repositories.parquet      # Selected repositories with pinned_sha & git_dir_sha256
│   │   ├── commits/                              # Per-repository PyDriller commit exports (50 files)
│   │   ├── churn/                                # Per-repository churn metric exports (50 files)
│   │   └── semgrep/                              # Per-repository Semgrep scan exports (49 files*)
│   ├── processed/
│   │   └── final_dataset.csv                     # Combined final dataset (49 repos, 2,450 commits, 120,472 rows)
│   ├── rq2_results_patched/
│   │   ├── full_findings.jsonl                   # Baseline Full-SAST findings on RQ2 sub-sample
│   │   ├── selective_findings.jsonl              # Selective-SAST findings on RQ2 sub-sample
│   │   ├── rq2_per_commit.csv                    # Commit-level TP/FN/FP counts (227 commits)
│   │   └── rq2_summary.json                      # Aggregated Precision, Recall, and F1 metrics
│   └── variance_results/
│       └── exclusion_log.csv                     # 20 commits excluded from RQ1 runtime pairing (0 flagged files)
├── figures/
│   ├── figure_2_code_churn_distribution_en.png   # Figure 2: Absolute churn distribution (log10 scale)
│   └── figure_3_execution_time_comparison_en.png # Figure 3: Full-SAST vs. Selective-SAST runtime boxplot
├── scripts/
│   ├── stage1_discovery.py                       # GitHub repository discovery & filtering
│   ├── stage2_cloning_final.py                   # Repository cloning & SHA pinning
│   ├── stage3_pydriller.py                       # Commit-level mining via PyDriller
│   ├── stage4_churn.py                           # Churn, entropy, staleness & path-flag computation
│   ├── stage5_semgrep.py                         # Semgrep baseline scanning
│   ├── stage6_analysis.py                        # Dataset integration & descriptive analysis
│   ├── stage7_evaluation.py                      # Core evaluation metrics
│   ├── stage8_variance.py                        # Paired runtime variance experiment
│   ├── variance_characterization_dual_v4.py      # 3x replicated paired runtime benchmark (RQ1)
│   ├── rq2_mini_analysis_patched.py              # Security retention evaluation (RQ2, Table 7)
│   ├── hitung_spearman.py                        # Spearman rank correlation validation
│   ├── hitung_median_final.py                    # Summary runtime statistics
│   ├── distribusi_code_churn.py                  # Generates Figure 2
│   ├── boxplot_waktu.py                          # Generates Figure 3
│   ├── investigate_mantinedev.py                 # Mantinedev pathological runtime investigation
│   └── archive/                                  # Earlier exploratory/recovery scripts
├── CITATION.cff
├── LICENSE
└── requirements.txt
```

> **Note on repository count:** `data/interim/commits/` and `data/interim/churn/` contain 50 candidate repositories, while `data/interim/semgrep/` and `data/processed/final_dataset.csv` contain **49 repositories**. One repository (`ElMassimo/iles`) was excluded during the Semgrep processing stage for not meeting consistent local execution criteria, as documented in Section 2.2 of the paper.

## Mapping to Paper Artifacts

| Paper Artifact | Primary Data / Output | Script(s) |
| :--- | :--- | :--- |
| Table 1 & Section 2.3 (Provenance & Pinned SHA) | `data/interim/02_selected_repositories.parquet` (`pinned_sha`, `git_dir_sha256`) | `stage1_discovery.py`, `stage2_cloning_final.py` |
| Table 3 & Table 4 (Dataset Summary & Volatility Clustering) | `data/processed/final_dataset.csv` | `stage3_pydriller.py` – `stage6_analysis.py`, `hitung_spearman.py` |
| Figure 2 (Absolute Churn Distribution) | `figures/figure_2_code_churn_distribution_en.png` | `distribusi_code_churn.py` |
| Table 5, Table 6, Table 8 & Figure 3 (RQ1 Runtime & Validation) | `data/variance_results/exclusion_log.csv`, `figures/figure_3_execution_time_comparison_en.png` *(see Archival Note)* | `variance_characterization_dual_v4.py`, `hitung_median_final.py`, `boxplot_waktu.py` |
| Section 3.3 (Mantinedev Anomaly Case Study) | — | `investigate_mantinedev.py` |
| Table 7 (RQ2 Security Retention) | `data/rq2_results_patched/` | `rq2_mini_analysis_patched.py` |

## Dataset Schema (`data/processed/final_dataset.csv`)

Each row represents a file-level modification within a commit (120,472 rows total). Key columns include:

- **Commit & author metadata:** `commit_timestamp_utc`, `repo_name`, `commit_hash`, `parent_hashes`, `author_id_hashed`, `author_email_domain`, `is_bot_author`, `is_revert`, `is_merge_commit`
- **File & churn metrics:** `file_path_at_commit`, `change_type`, `lines_added`, `lines_deleted`, `nloc_before`, `complexity_after`, `absolute_churn`, `churn_30d`, `churn_90d`, `relative_churn_30d`, `freq_30d`, `entropy_90d`, `days_since_last_mod`
- **Sensitive path flags:** `touches_config`, `touches_ci`, `touches_auth`, `touches_api`
- **Semgrep findings:** `median_execution_time_sec`, `rule_id`, `file_path`, `start_line`, `end_line`, `severity`

*Note: Columns `repo_name_x`, `repo_name_y`, `author_id_int`, and `dummy_count` are retained as-is from the pandas merge pipeline to preserve full compatibility with the analysis scripts.*

## Archival Note on RQ1 Raw Timing Logs

The raw per-replication wall-clock timing logs generated during the original WSL2 benchmark (`raw_timings_dual_v4_patched.csv` and `cv_summary_dual_v4.json`, used to compute Tables 5, 6, 8, and Figure 3) were lost during a local WSL environment recovery and are therefore not included in this archive. To preserve full methodological transparency without substituting mismatched post-publication timings:

- The exact benchmark implementation (`scripts/variance_characterization_dual_v4.py`), exclusion log (`data/variance_results/exclusion_log.csv`), repository SHA pins (`data/interim/02_selected_repositories.parquet`), and integrated dataset (`data/processed/final_dataset.csv`) are provided so researchers can independently reproduce the paired runtime benchmark.
- All RQ2 security retention artifacts (`data/rq2_results_patched/`) and the complete 49-repository dataset remain intact and directly verifiable.

## Setup & Reproduction

Install the required Python dependencies:

```bash
pip install -r requirements.txt
```

Run analysis scripts from the repository root directory, for example:

```bash
python scripts/hitung_spearman.py
python scripts/distribusi_code_churn.py
```

> **Note:** Re-running `stage2_cloning_final.py`, `stage5_semgrep.py`, `variance_characterization_dual_v4.py`, or `rq2_mini_analysis_patched.py` requires local Git clones of the 49 repositories (using `clone_url` and `pinned_sha` from `data/interim/02_selected_repositories.parquet`) and Semgrep CLI installed in your environment.

## Citation

If you use this dataset or code, please cite the published article (see `CITATION.cff`):

```bibtex
@article{hazimah2026selective_sast,
  author  = {Hazimah, Fadilah Tun and Faisal, Muhammad and Talib, Emil Agusalim Habi and Rahman, Titik Khawa Abd},
  title   = {CI/CD Pipeline Execution Time Optimization Using Code Churn-Based Selective-SAST on Jamstack Architecture},
  journal = {Journal of Informatics Unisla (JOUTICA)},
  year    = {2026},
  volume  = {11},
  number  = {2},
  pages   = {241--256},
  doi     = {10.30736/jti.v11i2.1695}
}
```

## License

- **Code (`scripts/`):** Released under the MIT License.
- **Dataset & Figures (`data/`, `figures/`):** Released under the Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0), aligned with the published article.