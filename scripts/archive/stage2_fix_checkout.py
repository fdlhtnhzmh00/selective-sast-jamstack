import subprocess
import pandas as pd
from pathlib import Path
from tqdm import tqdm

INPUT_FILE = Path("data/interim/02_selected_repositories.parquet")

def main():
    if not INPUT_FILE.exists():
        print("File metadata tidak ditemukan.")
        return
        
    df = pd.read_parquet(INPUT_FILE)
    
    print("Memperbaiki working tree (checkout) untuk 50 repositori...")
    pbar = tqdm(total=len(df), desc="Memulihkan file")
    
    for _, row in df.iterrows():
        repo_path = row['local_path']
        repo_name = row['full_name']
        
        # 1. Pastikan longpaths aktif di level repositori
        subprocess.run("git config core.longpaths true", cwd=repo_path, shell=True, capture_output=True)
        
        # 2. Paksa reset hard ke HEAD untuk mengembalikan semua file
        res = subprocess.run("git reset --hard HEAD", cwd=repo_path, shell=True, capture_output=True, text=True)
        
        if res.returncode != 0:
            print(f"\n[Warning] Sebagian file di {repo_name} gagal diekstrak karena karakter ilegal Windows. Git error: {res.stderr.strip()}")
            
        pbar.update(1)
        
    pbar.close()
    print("\nSelesai! Silakan cek folder 'repos' di File Explorer. Source code seharusnya sudah muncul.")

if __name__ == "__main__":
    main()