import os
import json
import time
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm

CHURN_DIR = Path("data/interim/churn")
REPOS_DIR = Path("repos")
OUTPUT_DIR = Path("data/interim/semgrep")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Aturan Semgrep sesuai metodologi
SEMGREP_RULES = [
    "p/javascript", 
    "p/typescript", 
    "p/react", 
    "p/security-audit", 
    "p/owasp-top-ten"
]
RULE_FLAGS = " ".join([f"--config {r}" for r in SEMGREP_RULES])
SCAN_RUNS = 3 # Standar metodologi (ubah ke 1 jika laptop overheat parah)

def get_ground_truth_corpus(df_churn):
    """Menentukan sampel komit untuk dipindai (Ground Truth Corpus)."""
    # 1. 10% Random Sample
    sample_10_pct = df_churn.sample(frac=0.10, random_state=42)
    
    # 2. Flagged by Baseline Selective-SAST
    # Simulasi pemicu: Churn > 75th pct, Entropy > 1.5, atau menyentuh path kritis
    pct_75 = df_churn['relative_churn_30d'].quantile(0.75) if not df_churn['relative_churn_30d'].isna().all() else 0
    
    flagged = df_churn[
        (df_churn['relative_churn_30d'] > pct_75) | 
        (df_churn['entropy_90d'] > 1.5) | 
        (df_churn['touches_config'] == True) | 
        (df_churn['touches_auth'] == True) | 
        (df_churn['touches_api'] == True) | 
        (df_churn['touches_ci'] == True) | 
        (df_churn['days_since_last_mod'] > 14)
    ]
    
    # 3. Non-flagged sample (5% untuk margin FN)
    non_flagged = df_churn[~df_churn.index.isin(flagged.index)].sample(frac=0.05, random_state=42)
    
    corpus = pd.concat([sample_10_pct, flagged, non_flagged]).drop_duplicates(subset=['commit_hash'])
    return corpus['commit_hash'].unique()

def scan_commit(repo_path, commit_hash):
    """Mengeksekusi Semgrep pada komit fisik sebanyak SCAN_RUNS kali."""
    # Checkout ke spesifik komit (reset hard untuk memastikan kebersihan file fisik)
    subprocess.run("git reset --hard", cwd=repo_path, shell=True, capture_output=True)
    res_checkout = subprocess.run(f"git checkout {commit_hash}", cwd=repo_path, shell=True, capture_output=True)
    
    if res_checkout.returncode != 0:
        return None, None # Gagal checkout, kemungkinan beda branch/tree
        
    execution_times = []
    findings = []
    
    for i in range(SCAN_RUNS):
        start_time = time.time()
        # Eksekusi Semgrep JSON output murni. --no-cache jika didukung, tapi kita bersihkan environment jika bisa
        cmd = f"semgrep scan {RULE_FLAGS} --json --quiet"
        res_semgrep = subprocess.run(cmd, cwd=repo_path, shell=True, capture_output=True, text=True)
        end_time = time.time()
        
        execution_times.append(end_time - start_time)
        
        # Parse findings hanya dari run pertama
        if i == 0 and res_semgrep.stdout:
            try:
                out_data = json.loads(res_semgrep.stdout)
                for issue in out_data.get('results', []):
                    findings.append({
                        'rule_id': issue['check_id'],
                        'file_path': issue['path'],
                        'start_line': issue['start']['line'],
                        'end_line': issue['end']['line'],
                        'severity': issue['extra']['severity']
                    })
            except json.JSONDecodeError:
                pass
                
    median_time = np.median(execution_times)
    return median_time, findings

def main():
    parquet_files = list(CHURN_DIR.glob("*.parquet"))
    
    print(f"Memulai Tahap 5: Ground Truth SAST Scanning ({SCAN_RUNS} runs/commit)...")
    
    for file_path in parquet_files:
        repo_name = file_path.stem
        output_file = OUTPUT_DIR / f"{repo_name}_semgrep.parquet"
        
        if output_file.exists():
            continue # Checkpoint: Lewati jika repo ini sudah selesai di-scan
            
        repo_path = REPOS_DIR / repo_name
        if not repo_path.exists():
            continue
            
        df_churn = pd.read_parquet(file_path)
        if df_churn.empty:
            continue
            
        target_commits = get_ground_truth_corpus(df_churn)
        
        # Batasan pragmatis untuk mencegah laptop mati: maksimal 50 komit sampel per repo
        if len(target_commits) > 50:
            np.random.seed(42)
            target_commits = np.random.choice(target_commits, 50, replace=False)
            
        scan_results = []
        
        print(f"\nMemindai {repo_name} ({len(target_commits)} komit target)...")
        pbar = tqdm(total=len(target_commits), desc=f"Scan Progress", leave=False)
        
        for commit_hash in target_commits:
            median_time, findings = scan_commit(repo_path, commit_hash)
            
            if median_time is not None:
                # Simpan meta eksekusi
                if not findings:
                    scan_results.append({
                        'repo_name': repo_name,
                        'commit_hash': commit_hash,
                        'median_execution_time_sec': median_time,
                        'rule_id': None, 'file_path': None, 'start_line': None, 'end_line': None, 'severity': None
                    })
                else:
                    for f in findings:
                        row = {
                            'repo_name': repo_name,
                            'commit_hash': commit_hash,
                            'median_execution_time_sec': median_time
                        }
                        row.update(f)
                        scan_results.append(row)
                        
            pbar.update(1)
            
        pbar.close()
        
        # Kembalikan ke HEAD agar tidak berantakan
        subprocess.run("git checkout -", cwd=repo_path, shell=True, capture_output=True)
        
        if scan_results:
            pd.DataFrame(scan_results).to_parquet(output_file, index=False)

    print("\nTahap 5 Selesai! Semua pemindaian Semgrep telah dicatat dan disimpan.")

if __name__ == "__main__":
    main()