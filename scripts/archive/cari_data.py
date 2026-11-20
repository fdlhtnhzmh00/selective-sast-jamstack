import pandas as pd
import glob
import os

print("Mencari file CSV yang berisi metrik komparasi 225 komit...")
print("-" * 50)

# Mencari semua file CSV di dalam folder data
for file_path in glob.glob('data/**/*.csv', recursive=True):
    try:
        df = pd.read_csv(file_path)
        # Mencari file yang jumlah barisnya mendekati 225 atau 245
        if 200 <= len(df) <= 300:
            print(f"[KANDIDAT DITEMUKAN] File : {file_path}")
            print(f"                     Baris: {len(df)}")
            print(f"                     Kolom: {list(df.columns)[:7]}\n")
    except Exception:
        continue

print("Pencarian selesai.")