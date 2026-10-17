import os
import shutil
import subprocess
import hashlib
import stat
import time
import pandas as pd
from pathlib import Path
from tqdm import tqdm

INPUT_FILE = Path("data/interim/01_repositories_metadata.parquet")
OUTPUT_FILE = Path("data/interim/02_selected_repositories.parquet")
REPOS_DIR = Path("repos")
TARGET_N = 50 # Harus mencapai n >= 50 sesuai standar minimal [cite: 37]

def force_rmtree(target_path, max_retries=5):
    def remove_readonly(func, path, _):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass
            
    for attempt in range(max_retries):
        if not os.path.exists(target_path):
            return
        try:
            shutil.rmtree(target_path, onerror=remove_readonly)
            return
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                try:
                    subprocess.run(f'rmdir /S /Q "{target_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

def check_ic_criteria_windows(repo_path):
    try:
        # IC3: Total commits >= 200 
        res_commits = subprocess.run("git rev-list --count HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
        if not res_commits.stdout.strip().isdigit() or int(res_commits.stdout.strip()) < 200:
            return False
            
        # IC4: Distinct authors >= 3 
        res_authors = subprocess.run('git log --format="%aN"', cwd=repo_path, shell=True, capture_output=True, text=True)
        authors = set([a.strip() for a in res_authors.stdout.strip().split('\n') if a.strip()])
        if len(authors) < 3:
            return False

        # IC6: CI/CD workflow present 
        ci_paths = [".github/workflows", ".gitlab-ci.yml", "netlify.toml", ".circleci/config.yml"]
        if not any((repo_path / path).exists() for path in ci_paths):
            return False

        return True
    except Exception:
        return False

def get_dir_hash(dir_path):
    sha256 = hashlib.sha256()
    for root, _, files in os.walk(dir_path):
        for names in sorted(files):
            filepath = os.path.join(root, names)
            try:
                with open(filepath, 'rb') as f:
                    while chunk := f.read(8192):
                        sha256.update(chunk)
            except Exception:
                continue
    return sha256.hexdigest()

def main():
    df_raw = pd.read_parquet(INPUT_FILE)
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Stratified Sampling: Acak data untuk menghindari dominasi satu framework [cite: 42]
    df_shuffled = df_raw.sample(frac=1, random_state=42).reset_index(drop=True)
    
    selected_repos = []
    
    # Checkpoint recovery: baca yang sudah tersimpan sebelumnya
    if OUTPUT_FILE.exists():
        try:
            existing_df = pd.read_parquet(OUTPUT_FILE)
            selected_repos = existing_df.to_dict('records')
        except Exception:
            pass
            
    print("Memulai Tahap 2: Final Windows-Proof Cloning...")
    pbar = tqdm(total=TARGET_N, desc="Repositori Tervalidasi", initial=len(selected_repos))
    
    for _, row in df_shuffled.iterrows():
        if len(selected_repos) >= TARGET_N:
            break
            
        repo_name = row['full_name']
        
        # Lewati jika sudah ada di dalam list valid
        if any(r.get('full_name') == repo_name for r in selected_repos):
            continue
            
        clone_url = row['clone_url']
        safe_name = repo_name.replace("/", "_")
        repo_path = REPOS_DIR / safe_name
        
        if repo_path.exists():
            force_rmtree(repo_path)
            
        clone_cmd = f"git clone --no-single-branch {clone_url} {repo_path}"
        try:
            res = subprocess.run(clone_cmd, shell=True, timeout=300, capture_output=True, text=True)
            if res.returncode != 0:
                force_rmtree(repo_path)
                continue
        except subprocess.TimeoutExpired:
            force_rmtree(repo_path)
            continue
        
        if not repo_path.exists():
            continue
            
        if check_ic_criteria_windows(repo_path):
            pinned_sha = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True).stdout.strip()
            git_hash = get_dir_hash(repo_path / ".git")
            
            repo_data = row.to_dict()
            repo_data['pinned_sha'] = pinned_sha
            repo_data['git_dir_sha256'] = git_hash
            repo_data['local_path'] = str(repo_path)
            
            selected_repos.append(repo_data)
            
            # Simpan data setiap kali 1 repositori valid ditemukan (Idempoten)
            pd.DataFrame(selected_repos).to_parquet(OUTPUT_FILE, index=False)
            pbar.update(1)
        else:
            force_rmtree(repo_path)

    pbar.close()
    
    if len(selected_repos) >= TARGET_N:
        print(f"\nSelesai! {len(selected_repos)} repositori valid telah diamankan ke {OUTPUT_FILE}")
    else:
        print(f"\nProses berhenti. Baru terkumpul {len(selected_repos)} repositori.")

if __name__ == "__main__":
    main()