import os
import shutil
import subprocess
import hashlib
import stat
import time # Tambahkan ini
import pandas as pd
from pathlib import Path
from tqdm import tqdm

INPUT_FILE = Path("data/interim/01_repositories_metadata.parquet")
OUTPUT_FILE = Path("data/interim/02_selected_repositories.parquet")
REPOS_DIR = Path("repos")

TARGET_N = 50

def run_cmd(cmd, cwd):
    """Menjalankan command shell dan mengembalikan outputnya."""
    try:
        result = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

def check_ic_criteria(repo_path):
    """Memverifikasi IC3, IC4, dan IC6 secara lokal."""
    # IC3: Total commits >= 200
    commit_count_str = run_cmd("git rev-list --count HEAD", repo_path)
    if not commit_count_str or int(commit_count_str) < 200:
        return False
        
    # IC4: Distinct authors >= 3
    authors_str = run_cmd("git log --format='%aN' | sort -u | wc -l", repo_path)
    if not authors_str or int(authors_str) < 3:
        return False

    # IC6: CI/CD workflow present
    ci_paths = [
        ".github/workflows",
        ".gitlab-ci.yml",
        "netlify.toml",
        ".circleci/config.yml"
    ]
    has_ci = any((repo_path / path).exists() for path in ci_paths)
    if not has_ci:
        return False

    return True

def get_dir_hash(dir_path):
    """Menghitung SHA-256 dari direktori git untuk validitas (Tahap 2)."""
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
def force_rmtree(target_path, max_retries=5):
    """
    Menghapus direktori secara paksa di Windows dengan mekanisme retry.
    Menangani file read-only dan file yang sedang dikunci sementara oleh OS/Antivirus.
    """
    def remove_readonly(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass # Abaikan error sementara, biarkan retry loop yang menangani

    for attempt in range(max_retries):
        if not os.path.exists(target_path):
            return
        try:
            shutil.rmtree(target_path, onerror=remove_readonly)
            return # Penghapusan berhasil
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2) # Tunggu 2 detik agar proses lain melepaskan file
            else:
                # Opsi terakhir: gunakan command bawaan Windows secara paksa
                try:
                    subprocess.run(f'rmdir /S /Q "{target_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    print(f"\n[Warning] Gagal total menghapus {target_path}. Melanjutkan proses...")

def main():
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} tidak ditemukan.")
        return

    df_raw = pd.read_parquet(INPUT_FILE)
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Stratified Sampling: Mengacak urutan per SSG
    df_shuffled = df_raw.sample(frac=1, random_state=42).reset_index(drop=True)
    
    selected_repos = []
    
    print("Memulai Tahap 2: Cloning & Strict Filtering...")
    
    pbar = tqdm(total=TARGET_N, desc="Repositori Tervalidasi")
    
    for _, row in df_shuffled.iterrows():
        if len(selected_repos) >= TARGET_N:
            break
            
        repo_name = row['full_name']
        clone_url = row['clone_url']
        safe_name = repo_name.replace("/", "_")
        repo_path = REPOS_DIR / safe_name
        
        # Hapus jika folder sudah ada (idempotensi)
        force_rmtree(repo_path)
            
        # Clone repository dengan Timeout dan Error Tracking
        clone_cmd = f"git clone --no-single-branch {clone_url} {repo_path}"
        try:
            # Beri batas waktu maksimal 300 detik (5 menit) per repositori
            result = subprocess.run(clone_cmd, shell=True, timeout=300, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"\n[Warning] Gagal clone {repo_name}. Git error: {result.stderr.strip()}")
                force_rmtree(repo_path)
                continue
        except subprocess.TimeoutExpired:
            print(f"\n[Timeout] Proses clone {repo_name} macet lebih dari 5 menit. Dilewati.")
            force_rmtree(repo_path)
            continue
        
        if not repo_path.exists():
            continue
            
        # Evaluasi Kriteria Inklusi
        if check_ic_criteria(repo_path):
            # Ambil Pinned SHA di HEAD
            pinned_sha = run_cmd("git rev-parse HEAD", repo_path)
            # Hitung SHA-256 dari .git
            git_hash = get_dir_hash(repo_path / ".git")
            
            repo_data = row.to_dict()
            repo_data['pinned_sha'] = pinned_sha
            repo_data['git_dir_sha256'] = git_hash
            repo_data['local_path'] = str(repo_path)
            
            selected_repos.append(repo_data)
            pbar.update(1)
        else:
            # Gagal filter: Hapus untuk menghemat SSD
            force_rmtree(repo_path)

    pbar.close()
    
    df_selected = pd.DataFrame(selected_repos)
    df_selected.to_parquet(OUTPUT_FILE, index=False)
    
    print(f"\nSelesai! {len(df_selected)} repositori valid telah di-clone dan diamankan.")
    print(f"Data meta tersimpan di: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()