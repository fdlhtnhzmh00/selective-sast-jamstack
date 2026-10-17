"""
RQ2 Mini-Analysis: Security Posture Retention — FULLY PATCHED VERSION
Untuk studi: Selective-SAST pada Pipeline CI/CD Jamstack
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

# ============================================================
# KONFIGURASI 
# ============================================================

DATASET_PATH = '/home/tecno/projects/selective-sast-jamstack/data/processed/final_dataset_6mo.csv'  
REPOS_DIR = Path('data/repos')
OUTPUT_DIR = Path('data/rq2_results_patched')              
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FULL_FINDINGS_FILE = OUTPUT_DIR / 'full_findings.jsonl'
SELECTIVE_FINDINGS_FILE = OUTPUT_DIR / 'selective_findings.jsonl'
PER_COMMIT_FILE = OUTPUT_DIR / 'rq2_per_commit.csv'
SUMMARY_FILE = OUTPUT_DIR / 'rq2_summary.json'

SAMPLE_FRACTION = 0.10
RANDOM_SEED = 42

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

VENDORED_PATH_PATTERNS = [
    re.compile(r'\.yarn/releases/'),
    re.compile(r'\.yarn/plugins/'),
    re.compile(r'\.yarn/sdks/'),
    re.compile(r'^node_modules/'),
    re.compile(r'/node_modules/'),
    re.compile(r'^vendor/'),
    re.compile(r'/vendor/'),
    re.compile(r'^dist/'),
    re.compile(r'/dist/'),
    re.compile(r'^build/'),
    re.compile(r'/build/'),
    re.compile(r'^out/'),
    re.compile(r'^\.next/'),
    re.compile(r'^\.nuxt/'),
    re.compile(r'^public/build/'),
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
    re.compile(r'\.map$'),
]

def normalize_path(path_str):
    if not isinstance(path_str, str):
        return None
    return path_str.replace('\\', '/').strip().lstrip('/')

def is_vendored_path(file_path):
    if not isinstance(file_path, str):
        return False
    fp = normalize_path(file_path)
    for pattern in VENDORED_PATH_PATTERNS:
        if pattern.search(fp):
            return True
    filename = os.path.basename(fp)
    for pattern in VENDORED_FILE_PATTERNS:
        if pattern.search(filename):
            return True
    return False

def compute_selective_flagged_files(df_repo_commit, churn_p75):
    df = df_repo_commit
    flag_churn   = df['relative_churn_30d'] > churn_p75
    flag_entropy = df['entropy_90d'] > ENTROPY_THRESHOLD
    flag_pattern = (df['touches_config'] | df['touches_auth']
                    | df['touches_api'] | df['touches_ci'])
    flag_stale   = df['days_since_last_mod'] > STALENESS_THRESHOLD_DAYS
    
    flagged_initial = df[flag_churn | flag_entropy | flag_pattern | flag_stale]
    
    valid_files = []
    for _, row in flagged_initial.iterrows():
        file_path = normalize_path(row['file_path_at_commit'])
        if not file_path:
            continue
        if is_vendored_path(file_path):
            continue
        valid_files.append(file_path)
    
    return list(set(valid_files))

def run_semgrep_full(repo_path, output_json):
    cmd = ['semgrep', 'scan', *SEMGREP_CONFIGS,
           '--metrics=off', '--no-rewrite-rule-ids',
           '--json', '-o', str(output_json),
           '--quiet', '--timeout=300', '.']
    try:
        result = subprocess.run(cmd, cwd=repo_path,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=1800)
        return result.returncode, None
    except subprocess.TimeoutExpired:
        return -1, 'timeout'

def run_semgrep_selective(repo_path, flagged_files, output_json):
    existing = []
    for f in flagged_files:
        if (repo_path / f).exists():
            existing.append(f)
    if not existing:
        return -1, 'no_existing_files'
    
    cmd = ['semgrep', 'scan', *SEMGREP_CONFIGS,
           '--metrics=off', '--no-rewrite-rule-ids',
           '--json', '-o', str(output_json),
           '--quiet', '--timeout=300', *existing]
    try:
        result = subprocess.run(cmd, cwd=repo_path,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, timeout=1800)
        return result.returncode, None
    except subprocess.TimeoutExpired:
        return -1, 'timeout'

def parse_semgrep_findings(json_path):
    if not json_path.exists():
        return []
    try:
        with open(json_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    
    findings = []
    for r in data.get('results', []):
        findings.append({
            'rule_id': r.get('check_id', ''),
            'file_path': normalize_path(r.get('path', '')),
            'start_line': r.get('start', {}).get('line', 0),
            'end_line': r.get('end', {}).get('line', 0),
            'severity': r.get('extra', {}).get('severity', 'UNKNOWN'),
        })
    return findings

def finding_key(f):
    return (f['rule_id'], f['file_path'], f['start_line'], f['end_line'])

def append_findings_jsonl(findings, repo, commit, mode, filepath):
    with open(filepath, 'a') as f:
        for finding in findings:
            record = {
                'repo_name': repo,
                'commit_hash': commit,
                'mode': mode,
                **finding,
            }
            f.write(json.dumps(record) + '\n')

# ============================================================
# 1. LOAD DATASET & SUB-SAMPLING
# ============================================================

print("="*60)
print("RQ2 MINI-ANALYSIS PATCHED: SECURITY POSTURE RETENTION")
print("="*60)

if not shutil.which('semgrep'):
    print("[FATAL] Semgrep tidak ditemukan")
    sys.exit(1)

df = pd.read_csv(DATASET_PATH)
df['churn_p75_repo'] = df.groupby('repo_name_x')['relative_churn_30d'].transform(
    lambda x: x.quantile(CHURN_PERCENTILE)
)
df_commits = df[['commit_hash', 'repo_name', 'repo_name_x']].drop_duplicates().reset_index(drop=True)

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

flagged_per_commit = {}
excluded_count = 0

for _, row in subsample_initial.iterrows():
    repo = row['repo_name_x']
    commit = row['commit_hash']
    sub = df[(df['repo_name_x'] == repo) & (df['commit_hash'] == commit)]
    if len(sub) == 0:
        continue
    p75 = sub['churn_p75_repo'].iloc[0]
    if pd.isna(p75): p75 = 0
    
    flagged = compute_selective_flagged_files(sub, p75)
    if len(flagged) == 0:
        excluded_count += 1
    else:
        flagged_per_commit[(repo, commit)] = flagged

valid_keys = set(flagged_per_commit.keys())
subsample = subsample_initial[
    subsample_initial.apply(
        lambda r: (r['repo_name_x'], r['commit_hash']) in valid_keys, axis=1
    )
].reset_index(drop=True)

unique_repos = subsample['repo_name_x'].unique()

# ============================================================
# 2. EKSEKUSI SCAN (WITH GROUND TRUTH PATCH)
# ============================================================

REPOS_DIR.mkdir(parents=True, exist_ok=True)
per_commit_records = []
TEMP_DIR = Path('/tmp/rq2_semgrep_output')
TEMP_DIR.mkdir(exist_ok=True)

for repo_idx, repo_url_name in enumerate(unique_repos, 1):
    repo_clean_name = subsample[subsample['repo_name_x'] == repo_url_name]['repo_name'].iloc[0]
    repo_commits = subsample[subsample['repo_name_x'] == repo_url_name]
    repo_path = REPOS_DIR / repo_clean_name

    shutil.rmtree(repo_path, ignore_errors=True)
    res = subprocess.run(['git', 'clone', '--quiet', f'https://github.com/{repo_url_name}.git', repo_clean_name], cwd=REPOS_DIR)
    if res.returncode != 0: continue

    for commit_idx, (_, row) in enumerate(repo_commits.iterrows(), 1):
        commit = row['commit_hash']
        flagged_files = flagged_per_commit[(repo_url_name, commit)]

        res_co = subprocess.run(['git', 'checkout', '-f', '--quiet', commit], cwd=repo_path, stderr=subprocess.PIPE)
        if res_co.returncode != 0: continue

        full_json = TEMP_DIR / f"full_{commit[:12]}.json"
        full_rc, full_err = run_semgrep_full(repo_path, full_json)
        raw_full_findings = parse_semgrep_findings(full_json) if full_rc != -1 else []

        sel_json = TEMP_DIR / f"sel_{commit[:12]}.json"
        sel_rc, sel_err = run_semgrep_selective(repo_path, flagged_files, sel_json)
        sel_findings = parse_semgrep_findings(sel_json) if sel_rc != -1 else []

        # --- LOGIKA GROUND TRUTH YANG BENAR ---
        repo_sub_df = df[(df['repo_name_x'] == repo_url_name) & (df['commit_hash'] == commit)]
        churned_files_raw = repo_sub_df['file_path_at_commit'].dropna().tolist()
        
        churned_files = set()
        for fp in churned_files_raw:
            nfp = normalize_path(fp)
            if nfp and not is_vendored_path(nfp):
                churned_files.add(nfp)

        full_findings = [f for f in raw_full_findings if f['file_path'] in churned_files]
        # ----------------------------------------

        append_findings_jsonl(full_findings, repo_url_name, commit, 'full', FULL_FINDINGS_FILE)
        append_findings_jsonl(sel_findings, repo_url_name, commit, 'selective', SELECTIVE_FINDINGS_FILE)

        full_keys = set(finding_key(f) for f in full_findings)
        sel_keys = set(finding_key(f) for f in sel_findings)
        tp = len(full_keys & sel_keys)
        fn = len(full_keys - sel_keys)
        fp = len(sel_keys - full_keys)

        record = {
            'repo_name': repo_url_name,
            'commit_hash': commit,
            'tp': tp, 'fn': fn, 'fp': fp,
            'full_findings_count': len(full_findings),
            'selective_findings_count': len(sel_findings)
        }
        per_commit_records.append(record)
        print(f"[{repo_clean_name}] {commit[:7]} -> TP:{tp} FN:{fn} FP:{fp}")

    shutil.rmtree(repo_path, ignore_errors=True)

pd.DataFrame(per_commit_records).to_csv(PER_COMMIT_FILE, index=False)
shutil.rmtree(TEMP_DIR, ignore_errors=True)

# ============================================================
# 3. ANALISIS 
# ============================================================

df_pc = pd.read_csv(PER_COMMIT_FILE)
total_tp = df_pc['tp'].sum()
total_fn = df_pc['fn'].sum()
total_fp = df_pc['fp'].sum()

recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

summary = {
    'aggregate': {'tp': int(total_tp), 'fn': int(total_fn), 'fp': int(total_fp), 'recall': recall, 'precision': precision, 'f1': f1}
}
with open(SUMMARY_FILE, 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\n==============================================")
print(f"RECALL FINAL    : {recall*100:.2f}%")
print(f"PRECISION FINAL : {precision*100:.2f}%")
print(f"F1 SCORE FINAL  : {f1*100:.2f}%")
print(f"==============================================")
