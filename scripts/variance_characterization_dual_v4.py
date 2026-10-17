"""
Variance Characterization Script — v4 (Vendored File Filter)

PERBAIKAN dari v3:
Berdasarkan investigasi anomali Mantinedev (Selective-SAST 1379s untuk
3MB yarn bundle file dengan pathological pattern matching), skrip ini
menambahkan FILTER FILE-LEVEL untuk vendored/generated/minified content.

Filter dirancang dari evidence empiris dan praktik industri:
- Path patterns: vendor/, dist/, build/, .yarn/releases/, node_modules/
- File patterns: *.min.js, *.bundle.js, *-lock.json, yarn.lock, etc.
- Size threshold: file >500KB cenderung minified (default exclusion)
- Line density: file >300 chars/line average → minified

Filter ini DIDOKUMENTASIKAN sebagai bagian dari predikat selective,
bukan disembunyikan.
"""

import os
import sys
import subprocess
import time
import random
import shutil
import json
import re
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ============================================================
# KONFIGURASI
# ============================================================

DATASET_PATH = 'data/processed/final_dataset.csv'
REPOS_DIR = Path('data/repos')
OUTPUT_DIR = Path('data/variance_results_v4')
RAW_TIMINGS_FILE = OUTPUT_DIR / 'raw_timings_dual_v4.csv'
SUMMARY_FILE = OUTPUT_DIR / 'cv_summary_dual_v4.json'
EXCLUSION_LOG_FILE = OUTPUT_DIR / 'exclusion_log_v4.csv'
VENDORED_LOG_FILE = OUTPUT_DIR / 'vendored_filtered_v4.csv'

SAMPLE_FRACTION = 0.10
RUNS_PER_COMMIT = 3
RANDOM_SEED = 42
TEST_MODE = False

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
# VENDORED FILE FILTER (Kontribusi paper)
# ============================================================

VENDORED_PATH_PATTERNS = [
    # Package manager bundles
    re.compile(r'\.yarn/releases/'),
    re.compile(r'\.yarn/plugins/'),
    re.compile(r'\.yarn/sdks/'),
    re.compile(r'^node_modules/'),
    re.compile(r'/node_modules/'),
    re.compile(r'^vendor/'),
    re.compile(r'/vendor/'),
    # Build artifacts
    re.compile(r'^dist/'),
    re.compile(r'/dist/'),
    re.compile(r'^build/'),
    re.compile(r'/build/'),
    re.compile(r'^out/'),
    re.compile(r'^\.next/'),
    re.compile(r'^\.nuxt/'),
    re.compile(r'^public/build/'),
    # Generated docs
    re.compile(r'^docs?/_build/'),
    re.compile(r'^site/'),
]

VENDORED_FILE_PATTERNS = [
    re.compile(r'\.min\.(js|css|mjs)$'),
    re.compile(r'\.bundle\.(js|mjs)$'),
    re.compile(r'\.chunk\.(js|mjs)$'),
    re.compile(r'-lock\.(json|yaml)$'),
    re.compile(r'^yarn\.lock$'),
    re.compile(r'^pnpm-lock\.yaml$'),
    re.compile(r'^package-lock\.json$'),
    re.compile(r'^Gemfile\.lock$'),
    re.compile(r'^composer\.lock$'),
    re.compile(r'^poetry\.lock$'),
    re.compile(r'\.map$'),  # source maps
]


def is_vendored_path(file_path):
    """Cek apakah path mengindikasikan vendored/generated content."""
    if not isinstance(file_path, str):
        return False, None
    
    for pattern in VENDORED_PATH_PATTERNS:
        if pattern.search(file_path):
            return True, f"path_pattern:{pattern.pattern}"
    
    filename = os.path.basename(file_path)
    for pattern in VENDORED_FILE_PATTERNS:
        if pattern.search(filename):
            return True, f"file_pattern:{pattern.pattern}"
    
    return False, None


def is_vendored_by_content(repo_path, file_path, size_threshold=500_000):
    """
    Cek apakah file kemungkinan vendored berdasarkan karakteristik konten:
    - Ukuran > 500KB untuk source code mencurigakan
    - Density karakter per baris > 300 (minified indicator)
    """
    full_path = repo_path / file_path
    if not full_path.exists():
        return False, None
    
    try:
        size = full_path.stat().st_size
        if size > size_threshold:
            # Cek density karakter per baris
            with open(full_path, 'rb') as f:
                content = f.read(min(100_000, size))  # baca sampai 100KB pertama
            
            lines = content.count(b'\n') or 1
            chars_per_line = len(content) / lines
            
            if chars_per_line > 300:
                return True, f"minified:{size}b/{int(chars_per_line)}cpl"
            if size > 1_000_000:  # >1MB pasti suspicious
                return True, f"oversize:{size}b"
    except (OSError, IOError):
        pass
    
    return False, None


# ============================================================
# UTILITAS LAINNYA (sama seperti v3)
# ============================================================

def normalize_path(path_str):
    if not isinstance(path_str, str):
        return None
    return path_str.replace('\\', '/').strip().lstrip('/')


def verify_environment():
    issues = []
    import platform
    is_windows = platform.system() == 'Windows'
    if is_windows:
        issues.append("[FATAL] Windows native tidak didukung. Gunakan WSL Ubuntu.")
    if not shutil.which('semgrep'):
        issues.append("[FATAL] Semgrep tidak ditemukan. pip install semgrep")
    if not shutil.which('git'):
        issues.append("[FATAL] Git tidak ditemukan.")
    if issues:
        print("\n".join(issues))
        return False
    print(f"[✓] Environment OK")
    return True


def log_system_state():
    if not HAS_PSUTIL:
        return {}
    state = {
        'cpu_percent': psutil.cpu_percent(interval=0.1),
        'mem_available_gb': round(psutil.virtual_memory().available / 1e9, 2),
    }
    try:
        battery = psutil.sensors_battery()
        if battery:
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
    cmd = ['semgrep', 'scan', *SEMGREP_CONFIGS,
           '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
           '--timeout=300', '.']
    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, cwd=repo_path,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=1800)
        return time.perf_counter() - start, result.returncode, None
    except subprocess.TimeoutExpired:
        return None, -1, 'timeout'


def run_semgrep_selective(repo_path, flagged_files):
    existing = []
    for f in flagged_files:
        normalized = normalize_path(f)
        if normalized and (repo_path / normalized).exists():
            existing.append(normalized)
    if not existing:
        return None, -1, 'no_existing_files'
    
    cmd = ['semgrep', 'scan', *SEMGREP_CONFIGS,
           '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
           '--timeout=300', *existing]
    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, cwd=repo_path,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=1800)
        return time.perf_counter() - start, result.returncode, None
    except subprocess.TimeoutExpired:
        return None, -1, 'timeout'


def compute_selective_flagged_files(df_repo_commit, churn_p75, repo_path=None):
    """
    Identifikasi file ter-flag dengan filter vendored.
    Return: (flagged_files, vendored_filtered_records)
    """
    df = df_repo_commit
    flag_churn   = df['relative_churn_30d'] > churn_p75
    flag_entropy = df['entropy_90d'] > ENTROPY_THRESHOLD
    flag_pattern = (df['touches_config'] | df['touches_auth']
                    | df['touches_api'] | df['touches_ci'])
    flag_stale   = df['days_since_last_mod'] > STALENESS_THRESHOLD_DAYS
    
    flagged_initial = df[flag_churn | flag_entropy | flag_pattern | flag_stale]
    
    valid_files = []
    vendored_filtered = []
    
    for _, row in flagged_initial.iterrows():
        file_path = normalize_path(row['file_path_at_commit'])
        if not file_path:
            continue
        
        # Filter level 1: path pattern
        is_v, reason = is_vendored_path(file_path)
        if is_v:
            vendored_filtered.append({
                'file_path': file_path,
                'filter_reason': reason,
                'commit_hash': row['commit_hash'],
                'repo_name': row['repo_name_x'],
            })
            continue
        
        # Filter level 2: content-based (jika repo_path tersedia)
        if repo_path:
            is_v, reason = is_vendored_by_content(repo_path, file_path)
            if is_v:
                vendored_filtered.append({
                    'file_path': file_path,
                    'filter_reason': reason,
                    'commit_hash': row['commit_hash'],
                    'repo_name': row['repo_name_x'],
                })
                continue
        
        valid_files.append(file_path)
    
    return list(set(valid_files)), vendored_filtered


# ============================================================
# MAIN PIPELINE
# ============================================================

print("="*60)
print("VARIANCE CHARACTERIZATION v4 — DENGAN VENDORED FILTER")
print("="*60)
print(f"Mulai: {datetime.now().isoformat()}\n")

if not verify_environment():
    sys.exit(1)

if TEST_MODE:
    print("\n[TEST MODE AKTIF]")

# Load dataset
print(f"\n[1] Loading {DATASET_PATH}...")
df = pd.read_csv(DATASET_PATH)
df['churn_p75_repo'] = df.groupby('repo_name_x')['relative_churn_30d'].transform(
    lambda x: x.quantile(CHURN_PERCENTILE)
)

df_commits = df[['commit_hash', 'repo_name', 'repo_name_x']].drop_duplicates().reset_index(drop=True)
print(f"    Total commit unik: {len(df_commits)}")
print(f"    Total repo unik  : {df_commits['repo_name_x'].nunique()}")

# Sub-sampling
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

# Pra-filtering DENGAN vendored filter (level 1: path-based)
print(f"\n[3] Pra-filtering dengan vendored detection (path-based)...")
print(f"    Path patterns yang difilter:")
for p in VENDORED_PATH_PATTERNS[:5]:
    print(f"      - {p.pattern}")
print(f"      ... ({len(VENDORED_PATH_PATTERNS)} total)")

flagged_per_commit = {}
exclusion_records = []
all_vendored_filtered = []

for _, row in subsample_initial.iterrows():
    repo = row['repo_name_x']
    commit = row['commit_hash']
    sub = df[(df['repo_name_x'] == repo) & (df['commit_hash'] == commit)]
    if len(sub) == 0:
        exclusion_records.append({
            'repo_name': repo, 'commit_hash': commit,
            'reason': 'no_data', 'flagged_count': 0,
        })
        continue
    p75 = sub['churn_p75_repo'].iloc[0]
    if pd.isna(p75): p75 = 0
    
    # Filter level 1 di pra-filtering (sebelum clone)
    flagged, vendored = compute_selective_flagged_files(sub, p75, repo_path=None)
    all_vendored_filtered.extend(vendored)
    
    if len(flagged) == 0:
        exclusion_records.append({
            'repo_name': repo, 'commit_hash': commit,
            'reason': 'no_files_flagged_after_vendored_filter',
            'flagged_count': 0,
            'vendored_filtered_count': len(vendored),
        })
    else:
        flagged_per_commit[(repo, commit)] = flagged

# Persist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
if exclusion_records:
    pd.DataFrame(exclusion_records).to_csv(EXCLUSION_LOG_FILE, index=False)
if all_vendored_filtered:
    pd.DataFrame(all_vendored_filtered).to_csv(VENDORED_LOG_FILE, index=False)

valid_keys = set(flagged_per_commit.keys())
subsample = subsample_initial[
    subsample_initial.apply(
        lambda r: (r['repo_name_x'], r['commit_hash']) in valid_keys, axis=1
    )
].reset_index(drop=True)

unique_repos = subsample['repo_name_x'].unique()
if TEST_MODE:
    unique_repos = unique_repos[:1]
    subsample = subsample[subsample['repo_name_x'].isin(unique_repos)].reset_index(drop=True)

total_commits = len(subsample)
total_scans = total_commits * 2 * RUNS_PER_COMMIT

print(f"\n[4] Hasil pra-filtering v4:")
print(f"    Sub-sampel awal           : {len(subsample_initial)}")
print(f"    Vendored files difilter   : {len(all_vendored_filtered)}")
print(f"    Dieksklusi (0 file flag)  : {len(exclusion_records)}")
print(f"    Sub-sampel valid          : {total_commits}")
print(f"    Repositori akan diuji     : {len(unique_repos)}")
print(f"    Total scan                : {total_scans}")

if 'median_execution_time_sec' in df.columns:
    typical = df.drop_duplicates('commit_hash')['median_execution_time_sec'].median()
    est_sec = total_commits * RUNS_PER_COMMIT * typical * 1.5
    print(f"    Estimasi durasi           : ~{est_sec/3600:.1f} jam")

# Tampilkan sample vendored yang difilter
if all_vendored_filtered:
    print(f"\n    Sample file yang difilter sebagai vendored:")
    for v in all_vendored_filtered[:10]:
        print(f"      - {v['file_path']:60s} [{v['filter_reason']}]")
    if len(all_vendored_filtered) > 10:
        print(f"      ... dan {len(all_vendored_filtered)-10} lagi")

input("\nTekan Enter untuk mulai, Ctrl+C untuk batal...")

# ============================================================
# 2. EKSEKUSI EKSPERIMEN (sama seperti v3)
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
    print(f"[+] CLONE: {repo_url_name} ({len(repo_commits)} commit)")
    res = subprocess.run(['git', 'clone', '--quiet', f'https://github.com/{repo_url_name}.git', repo_clean_name],
                        cwd=REPOS_DIR)
    if res.returncode != 0:
        print(f"    [!] Gagal clone, skip.")
        continue

    # Build task list
    tasks = []
    for _, row in repo_commits.iterrows():
        commit = row['commit_hash']
        flagged_files = flagged_per_commit[(repo_url_name, commit)]
        for mode in ['full', 'selective']:
            for run_id in range(1, RUNS_PER_COMMIT + 1):
                tasks.append({'commit': commit, 'mode': mode, 'run_id': run_id,
                             'flagged_files': flagged_files, 'flagged_count': len(flagged_files)})
    random.shuffle(tasks)

    # Warm-up
    first_commit = repo_commits.iloc[0]['commit_hash']
    print(f"[*] WARM-UP scan...")
    subprocess.run(['git', 'checkout', '-f', '--quiet', first_commit], cwd=repo_path)
    warmup = run_semgrep_full(repo_path)
    if warmup[0] is None:
        print(f"    [!] Warm-up error: {warmup[2]}")
        continue
    print(f"    Warm-up OK ({warmup[0]:.2f}s)")

    # Eksekusi
    print(f"[*] EKSEKUSI {len(tasks)} scan")
    last_commit = None
    for task_idx, task in enumerate(tasks, 1):
        commit = task['commit']
        if commit != last_commit:
            res_co = subprocess.run(['git', 'checkout', '-f', '--quiet', commit],
                                   cwd=repo_path, stderr=subprocess.PIPE)
            if res_co.returncode != 0:
                print(f"    [!] Checkout gagal {commit[:7]}")
                continue
            last_commit = commit

        sys_state = log_system_state()

        if task['mode'] == 'full':
            elapsed, rc, err = run_semgrep_full(repo_path)
        else:
            elapsed, rc, err = run_semgrep_selective(repo_path, task['flagged_files'])

        if elapsed is None:
            print(f"    [!] {commit[:7]} {task['mode']} run {task['run_id']}: {err}")
            continue

        record = {
            'timestamp': datetime.now().isoformat(),
            'repo_name': repo_url_name,
            'commit_hash': commit,
            'mode': task['mode'],
            'run_id': task['run_id'],
            'wall_clock_sec': round(elapsed, 4),
            'flagged_files_count': task['flagged_count'],
            'returncode': rc,
            **sys_state,
        }
        append_result(record, RAW_TIMINGS_FILE)

        if task_idx % 10 == 0 or task_idx == len(tasks):
            print(f"    [{task_idx}/{len(tasks)}] {commit[:7]} {task['mode']:9s} "
                  f"run {task['run_id']}: {elapsed:6.2f}s (flagged: {task['flagged_count']})")

    print(f"[-] DELETE: {repo_clean_name}")
    shutil.rmtree(repo_path, ignore_errors=True)

# ============================================================
# 3. ANALISIS
# ============================================================

print(f"\n{'='*60}")
print("ANALISIS HASIL v4")
print(f"{'='*60}")

if not RAW_TIMINGS_FILE.exists():
    sys.exit(1)

df_raw = pd.read_csv(RAW_TIMINGS_FILE)
print(f"Total measurement: {len(df_raw)}")

def cv_for_group(group):
    if len(group) < 2:
        return np.nan
    m, s = group['wall_clock_sec'].mean(), group['wall_clock_sec'].std(ddof=1)
    return (s / m * 100) if m > 0 else np.nan

def summarize(df_mode, label):
    cv = (df_mode.groupby(['repo_name', 'commit_hash'], group_keys=False)
                 .apply(cv_for_group).dropna())
    if len(cv) == 0:
        return {'mode': label, 'error': 'no_data'}
    return {
        'mode': label,
        'n_commits': int(len(cv)),
        'cv_median_pct': round(float(cv.median()), 3),
        'cv_p95_pct': round(float(cv.quantile(0.95)), 3),
        'cv_max_pct': round(float(cv.max()), 3),
        'wall_clock_median_sec': round(float(df_mode['wall_clock_sec'].median()), 3),
        'wall_clock_p95_sec': round(float(df_mode['wall_clock_sec'].quantile(0.95)), 3),
        'wall_clock_max_sec': round(float(df_mode['wall_clock_sec'].max()), 3),
    }

full = summarize(df_raw[df_raw['mode']=='full'], 'Full-SAST')
sel = summarize(df_raw[df_raw['mode']=='selective'], 'Selective-SAST')

time_saving = ((full.get('wall_clock_median_sec', 0) - sel.get('wall_clock_median_sec', 0)) /
               full.get('wall_clock_median_sec', 1) * 100)

summary = {
    'timestamp': datetime.now().isoformat(),
    'version': 'v4_with_vendored_filter',
    'sub_sample': {
        'initial': len(subsample_initial),
        'vendored_filtered_files': len(all_vendored_filtered),
        'excluded_no_flag': len(exclusion_records),
        'valid': total_commits,
    },
    'full_sast': full,
    'selective_sast': sel,
    'preview_rq1_time_saving_pct': round(time_saving, 2),
}

with open(SUMMARY_FILE, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nFull-SAST     : median CV {full.get('cv_median_pct',0):.2f}%, "
      f"P95 CV {full.get('cv_p95_pct',0):.2f}%")
print(f"Selective-SAST: median CV {sel.get('cv_median_pct',0):.2f}%, "
      f"P95 CV {sel.get('cv_p95_pct',0):.2f}%")
print(f"\nMedian wall-clock:")
print(f"  Full-SAST     : {full.get('wall_clock_median_sec',0):.2f}s")
print(f"  Selective-SAST: {sel.get('wall_clock_median_sec',0):.2f}s")
print(f"  Time saving   : {time_saving:.1f}%")
print(f"\nMax wall-clock (cek apakah outlier mantinedev hilang):")
print(f"  Full-SAST     : {full.get('wall_clock_max_sec',0):.2f}s")
print(f"  Selective-SAST: {sel.get('wall_clock_max_sec',0):.2f}s")

print(f"\n[✓] Output: {OUTPUT_DIR}")