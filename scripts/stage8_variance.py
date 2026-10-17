"""
Variance Characterization Script — Dual-Mode (Full vs Selective)
v3: Fix untuk WSL Ubuntu, path normalization yang lebih robust

Untuk dijalankan di:
  - WSL Ubuntu 22.04 native
  - Python 3.10+
  - Semgrep terinstall (pip install semgrep)
  - Project disalin ke filesystem Linux native (~/projects/...) untuk performa optimal

Sebelum jalankan:
  pip install pandas numpy psutil semgrep

Output:
  - data/variance_results/raw_timings_dual.csv
  - data/variance_results/cv_summary_dual.json
  - data/variance_results/exclusion_log.csv
"""

import os
import sys
import subprocess
import time
import random
import shutil
import json
from pathlib import Path, PurePosixPath
from datetime import datetime

import pandas as pd
import numpy as np

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[!] psutil tidak terinstall. Jalankan: pip install psutil")

# ============================================================
# KONFIGURASI
# ============================================================

DATASET_PATH = 'data/processed/final_dataset.csv'
REPOS_DIR = Path('data/repos')
OUTPUT_DIR = Path('data/variance_results')
RAW_TIMINGS_FILE = OUTPUT_DIR / 'raw_timings_dual.csv'
SUMMARY_FILE = OUTPUT_DIR / 'cv_summary_dual.json'
EXCLUSION_LOG_FILE = OUTPUT_DIR / 'exclusion_log.csv'

SAMPLE_FRACTION = 0.10
RUNS_PER_COMMIT = 3
RANDOM_SEED = 42

# === TEST MODE: set True untuk testing 1 repo saja ===
TEST_MODE = False  # ubah ke True untuk smoke test

# Semgrep ruleset — pinned (sama dengan eksperimen utama)
SEMGREP_CONFIGS = [
    '--config=p/javascript',
    '--config=p/typescript',
    '--config=p/react',
    '--config=p/nextjs',
    '--config=p/security-audit',
    '--config=p/owasp-top-ten',
    '--config=p/jwt',
]

ENTROPY_THRESHOLD = 1.5
STALENESS_THRESHOLD_DAYS = 14
CHURN_PERCENTILE = 0.75

# ============================================================
# UTILITAS
# ============================================================

def normalize_path(path_str):
    """
    Normalisasi path dari dataset (yang mungkin berformat Windows)
    ke format POSIX untuk WSL/Linux.

    Contoh:
      'test\\stubs\\nested.webc'  → 'test/stubs/nested.webc'
      'src/components/Foo.js'      → 'src/components/Foo.js'
    """
    if not isinstance(path_str, str):
        return None
    # Replace backslash dengan forward slash
    normalized = path_str.replace('\\', '/').strip()
    # Hapus leading slash jika ada (path harus relative dari repo root)
    normalized = normalized.lstrip('/')
    return normalized


def verify_environment():
    """Cek environment sebelum mulai. Return True jika OK."""
    issues = []

    # Cek OS
    import platform
    is_windows = platform.system() == 'Windows'
    is_wsl = 'microsoft' in platform.uname().release.lower() if not is_windows else False

    if is_windows:
        issues.append(
            "[FATAL] Anda menjalankan di Windows native!\n"
            "        Semgrep tidak mendukung Windows. Gunakan WSL Ubuntu.\n"
            "        Tutorial: https://learn.microsoft.com/windows/wsl/install"
        )

    # Cek Semgrep
    semgrep_path = shutil.which('semgrep')
    if not semgrep_path:
        issues.append(
            "[FATAL] Semgrep tidak ditemukan di PATH.\n"
            "        Install: pip install semgrep\n"
            "        Verifikasi: which semgrep && semgrep --version"
        )
    else:
        try:
            result = subprocess.run(
                ['semgrep', '--version'],
                capture_output=True, text=True, timeout=10
            )
            print(f"[✓] Semgrep version: {result.stdout.strip()}")
            print(f"[✓] Semgrep path   : {semgrep_path}")
        except Exception as e:
            issues.append(f"[FATAL] Semgrep error: {e}")

    # Cek Git
    git_path = shutil.which('git')
    if not git_path:
        issues.append("[FATAL] Git tidak ditemukan. Install: sudo apt install git")
    else:
        print(f"[✓] Git path: {git_path}")

    # Info environment
    print(f"[✓] Python : {sys.version.split()[0]}")
    print(f"[✓] Platform: {platform.system()} {platform.release()}")
    if is_wsl:
        print(f"[✓] WSL detected: OK")
    elif not is_windows:
        print(f"[i] Native Linux detected: OK")

    if issues:
        print("\n" + "="*60)
        print("ENVIRONMENT CHECK GAGAL")
        print("="*60)
        for issue in issues:
            print(issue)
        print()
        return False

    return True


def log_system_state():
    if not HAS_PSUTIL:
        return {}
    state = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'mem_available_gb': round(psutil.virtual_memory().available / 1e9, 2),
        'mem_percent': psutil.virtual_memory().percent,
    }
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            cpu_temps = [e.current for entries in temps.values()
                         for e in entries if e.current]
            if cpu_temps:
                state['cpu_temp_max'] = max(cpu_temps)
    except (AttributeError, OSError):
        pass
    try:
        battery = psutil.sensors_battery()
        if battery:
            state['battery_percent'] = battery.percent
            state['power_plugged'] = battery.power_plugged
    except (AttributeError, OSError):
        pass
    return state


def append_result(record, filepath):
    df_row = pd.DataFrame([record])
    if filepath.exists():
        df_row.to_csv(filepath, mode='a', header=False, index=False)
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        df_row.to_csv(filepath, mode='w', header=True, index=False)


def run_semgrep_full(repo_path):
    """Full-SAST: scan SELURUH repository."""
    cmd = [
        'semgrep', 'scan',
        *SEMGREP_CONFIGS,
        '--metrics=off',
        '--no-rewrite-rule-ids',
        '--quiet',
        '--timeout=300',
        '.',
    ]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=1800,
        )
        elapsed = time.perf_counter() - start
        return elapsed, result.returncode, None
    except subprocess.TimeoutExpired:
        return None, -1, 'timeout'
    except FileNotFoundError as e:
        return None, -1, f'semgrep_not_found: {e}'


def run_semgrep_selective(repo_path, flagged_files):
    """Selective-SAST: scan hanya file ter-flag."""
    # Filter file yang masih ada di working tree
    existing = []
    for f in flagged_files:
        normalized = normalize_path(f)
        if normalized and (repo_path / normalized).exists():
            existing.append(normalized)

    if not existing:
        return None, -1, 'no_existing_files'

    cmd = [
        'semgrep', 'scan',
        *SEMGREP_CONFIGS,
        '--metrics=off',
        '--no-rewrite-rule-ids',
        '--quiet',
        '--timeout=300',
        *existing,
    ]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=1800,
        )
        elapsed = time.perf_counter() - start
        return elapsed, result.returncode, None
    except subprocess.TimeoutExpired:
        return None, -1, 'timeout'
    except FileNotFoundError as e:
        return None, -1, f'semgrep_not_found: {e}'


def compute_selective_flagged_files(df_repo_commit, churn_p75):
    df = df_repo_commit
    flag_churn   = df['relative_churn_30d'] > churn_p75
    flag_entropy = df['entropy_90d'] > ENTROPY_THRESHOLD
    flag_pattern = (df['touches_config'] | df['touches_auth']
                    | df['touches_api'] | df['touches_ci'])
    flag_stale   = df['days_since_last_mod'] > STALENESS_THRESHOLD_DAYS

    flagged = df[flag_churn | flag_entropy | flag_pattern | flag_stale]
    files = (flagged['file_path_at_commit']
             .apply(normalize_path)
             .dropna()
             .unique()
             .tolist())
    return files


# ============================================================
# 0. ENVIRONMENT CHECK
# ============================================================

print("="*60)
print("VARIANCE CHARACTERIZATION — DUAL MODE (Full vs Selective)")
print("="*60)
print(f"Mulai: {datetime.now().isoformat()}")
print()

if not verify_environment():
    print("\n[!] Environment check gagal. Perbaiki masalah di atas dulu.")
    sys.exit(1)

if TEST_MODE:
    print("\n" + "!"*60)
    print("[TEST MODE AKTIF] Hanya menjalankan 1 repo pertama!")
    print("Set TEST_MODE = False untuk run penuh.")
    print("!"*60)

# ============================================================
# 1. LOAD DATASET, SUB-SAMPLING, & PRA-FILTERING
# ============================================================

print(f"\n[1] Loading {DATASET_PATH}...")
try:
    df = pd.read_csv(DATASET_PATH)
except Exception:
    df = pd.read_csv(DATASET_PATH, sep=';', on_bad_lines='skip')

df['churn_p75_repo'] = df.groupby('repo_name_x')['relative_churn_30d'].transform(
    lambda x: x.quantile(CHURN_PERCENTILE)
)

df_commits = df[['commit_hash', 'repo_name', 'repo_name_x']].drop_duplicates().reset_index(drop=True)
print(f"    Total commit unik: {len(df_commits)}")
print(f"    Total repo unik  : {df_commits['repo_name_x'].nunique()}")

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

sub_list = []
for repo, group in df_commits.groupby('repo_name_x'):
    if len(group) >= 10:
        sampled = group.sample(frac=SAMPLE_FRACTION, random_state=RANDOM_SEED)
    else:
        sampled = group.sample(n=min(1, len(group)), random_state=RANDOM_SEED)
    sub_list.append(sampled)
subsample_initial = pd.concat(sub_list, ignore_index=True)

print(f"\n[2] Sub-sampel awal: {len(subsample_initial)} commit")

# Pra-filtering: hitung file ter-flag, eksklusi commit dengan 0 file ter-flag
print(f"\n[3] Pra-filtering (predikat selective baseline)...")
flagged_per_commit = {}
exclusion_records = []

for _, row in subsample_initial.iterrows():
    repo = row['repo_name_x']
    commit = row['commit_hash']
    sub = df[(df['repo_name_x'] == repo) & (df['commit_hash'] == commit)]
    if len(sub) == 0:
        exclusion_records.append({
            'repo_name': repo, 'commit_hash': commit,
            'reason': 'no_data_in_dataset', 'flagged_count': 0,
        })
        continue
    p75 = sub['churn_p75_repo'].iloc[0]
    if pd.isna(p75):
        p75 = 0
    flagged = compute_selective_flagged_files(sub, p75)
    if len(flagged) == 0:
        exclusion_records.append({
            'repo_name': repo, 'commit_hash': commit,
            'reason': 'no_files_flagged_by_predicate', 'flagged_count': 0,
        })
    else:
        flagged_per_commit[(repo, commit)] = flagged

valid_keys = set(flagged_per_commit.keys())
subsample = subsample_initial[
    subsample_initial.apply(
        lambda r: (r['repo_name_x'], r['commit_hash']) in valid_keys, axis=1
    )
].reset_index(drop=True)

if exclusion_records:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(exclusion_records).to_csv(EXCLUSION_LOG_FILE, index=False)

unique_repos = subsample['repo_name_x'].unique()

# === TEST MODE: hanya ambil 1 repo ===
if TEST_MODE:
    unique_repos = unique_repos[:1]
    subsample = subsample[subsample['repo_name_x'].isin(unique_repos)].reset_index(drop=True)

total_commits = len(subsample)
total_scans = total_commits * 2 * RUNS_PER_COMMIT

print(f"\n[4] Hasil pra-filtering:")
print(f"    Sub-sampel awal           : {len(subsample_initial)}")
print(f"    Dieksklusi (0 file flag)  : {len(exclusion_records)}")
print(f"    Sub-sampel valid          : {total_commits}")
print(f"    Repositori akan diuji     : {len(unique_repos)}")
print(f"    Total scan                : {total_scans}")

if 'median_execution_time_sec' in df.columns:
    typical = df.drop_duplicates('commit_hash')['median_execution_time_sec'].median()
    est_sec = total_commits * RUNS_PER_COMMIT * typical * 1.5
    print(f"    Estimasi durasi           : ~{est_sec/3600:.1f} jam")

input("\nTekan Enter untuk mulai, Ctrl+C untuk batal...")

# ============================================================
# 2. EKSEKUSI EKSPERIMEN
# ============================================================

REPOS_DIR.mkdir(parents=True, exist_ok=True)

for repo_idx, repo_url_name in enumerate(unique_repos, 1):
    print(f"\n{'='*60}")
    print(f"[{repo_idx}/{len(unique_repos)}] {repo_url_name}")
    print(f"{'='*60}")

    repo_clean_name = subsample[subsample['repo_name_x'] == repo_url_name]['repo_name'].iloc[0]
    repo_commits = subsample[subsample['repo_name_x'] == repo_url_name]
    repo_path = REPOS_DIR / repo_clean_name

    shutil.rmtree(repo_path, ignore_errors=True)

    print(f"[+] CLONE: {repo_url_name} ({len(repo_commits)} commit valid)")
    clone_url = f'https://github.com/{repo_url_name}.git'
    res = subprocess.run(
        ['git', 'clone', '--quiet', clone_url, repo_clean_name],
        cwd=REPOS_DIR,
    )
    if res.returncode != 0:
        print(f"    [!] Gagal clone, skip.")
        continue

    # Build task list (commit × mode × run, urutan acak)
    tasks = []
    for _, row in repo_commits.iterrows():
        commit = row['commit_hash']
        flagged_files = flagged_per_commit[(repo_url_name, commit)]
        for mode in ['full', 'selective']:
            for run_id in range(1, RUNS_PER_COMMIT + 1):
                tasks.append({
                    'commit': commit,
                    'mode': mode,
                    'run_id': run_id,
                    'flagged_files': flagged_files,
                    'flagged_count': len(flagged_files),
                })
    random.shuffle(tasks)

    # Warm-up
    first_commit = repo_commits.iloc[0]['commit_hash']
    print(f"[*] WARM-UP scan (dibuang)...")
    res_co = subprocess.run(
        ['git', 'checkout', '-f', '--quiet', first_commit],
        cwd=repo_path, stderr=subprocess.PIPE,
    )
    if res_co.returncode == 0:
        warmup_result = run_semgrep_full(repo_path)
        if warmup_result[0] is None:
            print(f"    [!] Warm-up error: {warmup_result[2]}")
            print(f"    [!] Cek apakah Semgrep terinstall: which semgrep")
            sys.exit(1)
        else:
            print(f"    Warm-up OK ({warmup_result[0]:.2f}s, dibuang)")

    # Eksekusi
    print(f"[*] EKSEKUSI {len(tasks)} scan (urutan acak)")
    last_commit = None
    for task_idx, task in enumerate(tasks, 1):
        commit = task['commit']
        mode = task['mode']
        run_id = task['run_id']

        if commit != last_commit:
            res_co = subprocess.run(
                ['git', 'checkout', '-f', '--quiet', commit],
                cwd=repo_path, stderr=subprocess.PIPE,
            )
            if res_co.returncode != 0:
                print(f"    [!] Checkout gagal {commit[:7]}, skip.")
                continue
            last_commit = commit

        sys_state = log_system_state()

        if mode == 'full':
            elapsed, returncode, err = run_semgrep_full(repo_path)
        else:
            elapsed, returncode, err = run_semgrep_selective(
                repo_path, task['flagged_files']
            )

        if elapsed is None:
            print(f"    [!] {commit[:7]} {mode} run {run_id}: {err}")
            continue

        record = {
            'timestamp': datetime.now().isoformat(),
            'repo_name': repo_url_name,
            'commit_hash': commit,
            'mode': mode,
            'run_id': run_id,
            'wall_clock_sec': round(elapsed, 4),
            'flagged_files_count': task['flagged_count'],
            'returncode': returncode,
            **sys_state,
        }
        append_result(record, RAW_TIMINGS_FILE)

        if task_idx % 10 == 0 or task_idx == len(tasks):
            print(f"    [{task_idx}/{len(tasks)}] {commit[:7]} {mode:9s} "
                  f"run {run_id}: {elapsed:6.2f}s "
                  f"(flagged: {task['flagged_count']})")

    print(f"[-] DELETE: {repo_clean_name}")
    shutil.rmtree(repo_path, ignore_errors=True)


# ============================================================
# 3. ANALISIS HASIL
# ============================================================

print(f"\n{'='*60}")
print("ANALISIS MEASUREMENT ERROR ENVELOPE")
print(f"{'='*60}")

if not RAW_TIMINGS_FILE.exists():
    print("[!] Tidak ada data hasil.")
    sys.exit(1)

df_raw = pd.read_csv(RAW_TIMINGS_FILE)
print(f"Total measurement: {len(df_raw)}")
print(f"  Full-SAST     : {(df_raw['mode']=='full').sum()}")
print(f"  Selective-SAST: {(df_raw['mode']=='selective').sum()}")


def cv_for_group(group):
    if len(group) < 2:
        return np.nan
    mean = group['wall_clock_sec'].mean()
    std = group['wall_clock_sec'].std(ddof=1)
    return (std / mean * 100) if mean > 0 else np.nan


def summarize_mode(df_mode, label):
    cv_per_commit = (df_mode.groupby(['repo_name', 'commit_hash'])
                            .apply(cv_for_group).dropna())
    if len(cv_per_commit) == 0:
        return {'mode': label, 'error': 'no_valid_data'}
    return {
        'mode': label,
        'n_commits_valid': int(len(cv_per_commit)),
        'n_total_measurements': int(len(df_mode)),
        'cv_median_pct': round(float(cv_per_commit.median()), 3),
        'cv_p95_pct': round(float(cv_per_commit.quantile(0.95)), 3),
        'cv_p99_pct': round(float(cv_per_commit.quantile(0.99)), 3),
        'cv_max_pct': round(float(cv_per_commit.max()), 3),
        'cv_mean_pct': round(float(cv_per_commit.mean()), 3),
        'cv_std_pct': round(float(cv_per_commit.std(ddof=1)), 3),
        'wall_clock_median_sec': round(float(df_mode['wall_clock_sec'].median()), 3),
        'wall_clock_mean_sec': round(float(df_mode['wall_clock_sec'].mean()), 3),
        'wall_clock_p95_sec': round(float(df_mode['wall_clock_sec'].quantile(0.95)), 3),
    }


full_summary = summarize_mode(df_raw[df_raw['mode'] == 'full'], 'Full-SAST')
selective_summary = summarize_mode(df_raw[df_raw['mode'] == 'selective'], 'Selective-SAST')

median_full = full_summary.get('wall_clock_median_sec', 0)
median_sel = selective_summary.get('wall_clock_median_sec', 0)
time_saving_pct = ((median_full - median_sel) / median_full * 100) if median_full > 0 else 0

flag_stats = df_raw[df_raw['mode'] == 'selective']['flagged_files_count']
flag_distribution = {
    'min': int(flag_stats.min()) if len(flag_stats) else 0,
    'median': int(flag_stats.median()) if len(flag_stats) else 0,
    'mean': round(float(flag_stats.mean()), 2) if len(flag_stats) else 0,
    'p95': int(flag_stats.quantile(0.95)) if len(flag_stats) else 0,
    'max': int(flag_stats.max()) if len(flag_stats) else 0,
}

summary = {
    'timestamp': datetime.now().isoformat(),
    'sub_sample': {
        'initial': len(subsample_initial),
        'excluded_no_flag': len(exclusion_records),
        'valid': total_commits,
        'repositories_tested': len(unique_repos),
    },
    'runs_per_commit_per_mode': RUNS_PER_COMMIT,
    'random_seed': RANDOM_SEED,
    'predicate_config': {
        'entropy_threshold_bits': ENTROPY_THRESHOLD,
        'staleness_threshold_days': STALENESS_THRESHOLD_DAYS,
        'churn_percentile': CHURN_PERCENTILE,
    },
    'full_sast': full_summary,
    'selective_sast': selective_summary,
    'flagged_files_per_commit_distribution': flag_distribution,
    'preview_rq1_time_saving_pct': round(time_saving_pct, 2),
}

print(f"\n┌─ FULL-SAST ─────────────────────────────────")
if 'error' not in full_summary:
    print(f"│  Median CV         : ±{full_summary['cv_median_pct']:.2f}%")
    print(f"│  P95 CV            : ±{full_summary['cv_p95_pct']:.2f}%")
    print(f"│  Median wall-clock : {full_summary['wall_clock_median_sec']:.2f}s")
print(f"└──────────────────────────────────────────────")

print(f"\n┌─ SELECTIVE-SAST ─────────────────────────────")
if 'error' not in selective_summary:
    print(f"│  Median CV         : ±{selective_summary['cv_median_pct']:.2f}%")
    print(f"│  P95 CV            : ±{selective_summary['cv_p95_pct']:.2f}%")
    print(f"│  Median wall-clock : {selective_summary['wall_clock_median_sec']:.2f}s")
print(f"└──────────────────────────────────────────────")

print(f"\n┌─ DISTRIBUSI FILE TER-FLAG PER COMMIT ────────")
print(f"│  Min: {flag_distribution['min']}, Median: {flag_distribution['median']}, "
      f"Mean: {flag_distribution['mean']}, Max: {flag_distribution['max']}")
print(f"└──────────────────────────────────────────────")

print(f"\n┌─ PREVIEW RQ1 (estimasi awal) ────────────────")
print(f"│  Time saving (median): {time_saving_pct:.1f}%")
print(f"└──────────────────────────────────────────────")

with open(SUMMARY_FILE, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n[✓] Raw timings    : {RAW_TIMINGS_FILE}")
print(f"[✓] Summary JSON   : {SUMMARY_FILE}")
print(f"[✓] Exclusion log  : {EXCLUSION_LOG_FILE}")