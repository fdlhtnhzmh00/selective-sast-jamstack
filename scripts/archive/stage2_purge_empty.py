import os
import subprocess
import pandas as pd
from pathlib import Path

OUTPUT_FILE = Path("data/interim/02_selected_repositories.parquet")

def main():
    if not OUTPUT_FILE.exists():
        print("File metadata tidak ditemukan.")
        return
        
    df = pd.read_parquet(OUTPUT_FILE)
    valid_repos = []
    
    print("Mendeteksi dan membuang repositori kosong (EC4: Tool Incompatibility)...")
    for _, row in df.iterrows():
        repo_path = Path(row['local_path'])
        
        # Cek apakah ada file fisik selain folder .git
        is_populated = False
        if repo_path.exists():
            for item in os.listdir(repo_path):
                if item != '.git':
                    is_populated = True
                    break
                    
        if is_populated:
            valid_repos.append(row.to_dict())
        else:
            print(f"[Dibuang] {row['full_name']} - Gagal checkout di Windows.")
            # Hapus paksa folder menggunakan command Windows
            subprocess.run(f'rmdir /S /Q "{repo_path}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
    df_clean = pd.DataFrame(valid_repos)
    df_clean.to_parquet(OUTPUT_FILE, index=False)
    
    kekurangan = 50 - len(df_clean)
    print(f"\nSisa repositori valid: {len(df_clean)}/50.")
    if kekurangan > 0:
        print(f"Sistem butuh {kekurangan} repositori pengganti.")
        print("Langkah selanjutnya: Jalankan ulang 'python scripts/stage2_cloning_final.py'")

if __name__ == "__main__":
    main()