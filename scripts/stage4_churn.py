import os
import math
import numpy as np
import pandas as pd
from pathlib import Path
from tqdm import tqdm

INPUT_DIR = Path("data/interim/commits")
OUTPUT_DIR = Path("data/interim/churn")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def calculate_entropy(authors_series):
    """Menghitung Developer Entropy (Hassan, 2009) dari sebuah window."""
    if len(authors_series) == 0:
        return 0.0
    counts = authors_series.value_counts()
    probs = counts / len(authors_series)
    entropy = -sum(p * math.log2(p) for p in probs if p > 0)
    return entropy

def process_repository_churn(file_path):
    output_path = OUTPUT_DIR / file_path.name
    if output_path.exists():
        return True # Idempoten: lewati jika sudah diproses

    df = pd.read_parquet(file_path)
    if df.empty:
        return True

    # Pastikan timestamp dalam format datetime dan diurutkan
    df['commit_timestamp_utc'] = pd.to_datetime(df['commit_timestamp_utc'])
    df = df.sort_values(['file_path_at_commit', 'commit_timestamp_utc']).reset_index(drop=True)

    # Konversi paksa ke tipe numerik untuk menghindari DataError
    df['lines_added'] = pd.to_numeric(df['lines_added'], errors='coerce').fillna(0)
    df['lines_deleted'] = pd.to_numeric(df['lines_deleted'], errors='coerce').fillna(0)
    df['nloc_before'] = pd.to_numeric(df['nloc_before'], errors='coerce').fillna(0)

    # Absolute Churn = lines_added + lines_deleted
    df['absolute_churn'] = df['lines_added'] + df['lines_deleted']

    # Persiapkan kolom output
    df['churn_30d'] = 0.0
    df['churn_90d'] = 0.0
    df['freq_30d'] = 0
    df['entropy_90d'] = 0.0
    df['days_since_last_mod'] = 999.0

    # Kalkulasi efisien berbasis window per file
    # Menggunakan metode iterasi optimasi pandas untuk menghitung rolling metrics
    grouped = df.groupby('file_path_at_commit')
    
    # Kita buat list untuk menampung hasil agar lebih cepat dari .apply()
    results = []
    
    for file_name, group in grouped:
        group = group.sort_values('commit_timestamp_utc')
        group = group.set_index('commit_timestamp_utc')
        
        # Hitung jarak hari antar komit
        time_diff = group.index.to_series().diff().dt.total_seconds() / 86400.0
        days_since = time_diff.fillna(999.0).values
        
        # Trik: Konversi author string ke angka integer agar Pandas tidak crash
        group['author_id_int'] = group['author_id_hashed'].astype('category').cat.codes
        group['dummy_count'] = 1 # Dummy numerik untuk menghitung frekuensi komit
        
        # Rolling 30 Days: Absolute Churn & Change Frequency
        rolling_30 = group.rolling('30D')
        churn_30 = rolling_30['absolute_churn'].sum().fillna(0).values
        freq_30 = rolling_30['dummy_count'].sum().fillna(0).values
        
        # Fungsi entropy berbasis Numpy array (Sangat cepat dan kebal error)
        def calc_entropy_numeric(x):
            if len(x) == 0: return 0.0
            _, counts = np.unique(x, return_counts=True)
            probs = counts / len(x)
            return -np.sum(probs * np.log2(probs))
            
        # Rolling 90 Days: Developer Entropy
        rolling_90 = group.rolling('90D')
        entropy_90 = rolling_90['author_id_int'].apply(calc_entropy_numeric, raw=True).fillna(0).values
        
        # Relatif Churn dihitung di akhir: churn_30 / nloc_before
        nloc = group['nloc_before'].replace(0, 1).values # Hindari division by zero
        
        group_res = group.reset_index()
        group_res['churn_30d'] = churn_30
        group_res['relative_churn_30d'] = churn_30 / nloc
        group_res['freq_30d'] = freq_30
        group_res['entropy_90d'] = entropy_90
        group_res['days_since_last_mod'] = days_since
        
        results.append(group_res)

    if results:
        final_df = pd.concat(results, ignore_index=True)
        # Urutkan kembali berdasarkan waktu komit asli
        final_df = final_df.sort_values('commit_timestamp_utc').reset_index(drop=True)
        final_df.to_parquet(output_path, index=False)
    
    return True

def main():
    parquet_files = list(INPUT_DIR.glob("*.parquet"))
    
    print("Memulai Tahap 4: Churn Metric Computation...")
    pbar = tqdm(total=len(parquet_files), desc="Menghitung Metrik")
    
    for file_path in parquet_files:
        try:
            process_repository_churn(file_path)
        except Exception as e:
            print(f"\n[Error] Gagal memproses {file_path.name}: {e}")
        pbar.update(1)
        
    pbar.close()
    print("\nTahap 4 Selesai! Semua metrik Code Churn historis telah dihitung dan dinormalisasi.")

if __name__ == "__main__":
    main()