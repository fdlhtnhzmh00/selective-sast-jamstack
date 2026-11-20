import os
import subprocess
import hashlib
import pandas as pd
from pathlib import Path

INPUT_FILE = Path("data/interim/01_repositories_metadata.parquet")
OUTPUT_FILE = Path("data/interim/02_selected_repositories.parquet")
REPOS_DIR = Path("repos")
TARGET_N = 50

def check_ic_criteria_windows(repo_path):
    """Verifikasi IC3, IC4, IC6 menggunakan pure Python untuk kompatibilitas Windows."""
    try:
        # IC3: Total commits >= 200
        res_commits = subprocess.run("git rev-list --count HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
        if not res_commits.stdout.strip().isdigit() or int(res_commits.stdout.strip()) < 200:
            return False
            
        # IC4: Distinct authors >= 3
        res_authors = subprocess.run('git log --format="%aN"', cwd=repo_path, shell=True, capture_output=True, text=True)
        authors = set([author.strip() for author in res_authors.stdout.strip().split('\n') if author.strip()])
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
    print("Memulai proses recovery dataset lokal...")
    df_raw = pd.read_parquet(INPUT_FILE)
    
    # Buat dictionary untuk pencarian metadata cepat
    metadata_dict = {row['full_name'].replace("/", "_"): row.to_dict() for _, row in df_raw.iterrows()}
    
    selected_repos = []
    
    # Loop melalui folder yang sudah terunduh di dalam direktori repos/
    for folder_name in os.listdir(REPOS_DIR):
        if len(selected_repos) >= TARGET_N:
            break
            
        repo_path = REPOS_DIR / folder_name
        if not repo_path.is_dir() or not (repo_path / ".git").exists():
            continue
            
        if check_ic_criteria_windows(repo_path):
            print(f"[Valid] {folder_name} lolos verifikasi.")
            pinned_sha = subprocess.run("git rev-parse HEAD", cwd=repo_path, shell=True, capture_output=True, text=True).stdout.strip()
            git_hash = get_dir_hash(repo_path / ".git")
            
            repo_data = metadata_dict.get(folder_name, {})
            if not repo_data:
                repo_data = {'full_name': folder_name.replace("_", "/")} # Fallback
                
            repo_data['pinned_sha'] = pinned_sha
            repo_data['git_dir_sha256'] = git_hash
            repo_data['local_path'] = str(repo_path)
            
            selected_repos.append(repo_data)
        else:
            print(f"[Gagal] {folder_name} tidak memenuhi kriteria.")

    df_selected = pd.DataFrame(selected_repos)
    df_selected.to_parquet(OUTPUT_FILE, index=False)
    
    print(f"\nSelesai! Berhasil menyelamatkan {len(df_selected)} repositori valid.")
    print(f"Data meta tersimpan di: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()