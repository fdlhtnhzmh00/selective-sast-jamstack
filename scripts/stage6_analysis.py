import os
import glob
import pandas as pd

CHURN_DIR = os.path.join('data', 'interim', 'churn')
SEMGREP_DIR = os.path.join('data', 'interim', 'semgrep')
OUTPUT_DIR = os.path.join('data', 'processed')
OUTPUT_CSV = os.path.join(OUTPUT_DIR, 'final_dataset.csv')

os.makedirs(OUTPUT_DIR, exist_ok=True)

semgrep_files = glob.glob(os.path.join(SEMGREP_DIR, '*_semgrep.parquet'))
all_data = []

print('Memulai Tahap 6: Agregasi dan Pembentukan Final Dataset...')

for semgrep_file in semgrep_files:
    filename = os.path.basename(semgrep_file)
    repo_name = filename.replace('_semgrep.parquet', '')
    
    # REVISI: Nama file churn disesuaikan dengan fakta di lapangan
    churn_file = os.path.join(CHURN_DIR, f'{repo_name}.parquet')

    if not os.path.exists(churn_file):
        print(f"Melewati {repo_name}: File churn tidak ditemukan.")
        continue

    try:
        df_semgrep = pd.read_parquet(semgrep_file)
        df_churn = pd.read_parquet(churn_file)

        # Cari kolom hash untuk penggabungan
        if 'commit_hash' in df_semgrep.columns and 'commit_hash' in df_churn.columns:
            df_merged = pd.merge(df_churn, df_semgrep, on='commit_hash', how='inner')
        elif 'hash' in df_semgrep.columns and 'hash' in df_churn.columns:
            df_merged = pd.merge(df_churn, df_semgrep, on='hash', how='inner')
        else:
            # Jika nama kolom beda, gabungkan paksa berdasarkan urutan baris
            df_merged = pd.concat([df_churn.reset_index(drop=True), df_semgrep.reset_index(drop=True)], axis=1)
        
        df_merged['repo_name'] = repo_name
        all_data.append(df_merged)
        
    except Exception as e:
        print(f'Error memproses {repo_name}: {e}')

if all_data:
    final_df = pd.concat(all_data, ignore_index=True)
    # Hapus kolom duplikat jika ada
    final_df = final_df.loc[:, ~final_df.columns.duplicated()]
    final_df.to_csv(OUTPUT_CSV, index=False)
    
    print(f'\nTAHAP 6 SELESAI!')
    print(f'Dataset akhir berhasil disimpan di: {OUTPUT_CSV}')
    print(f'Total baris data: {len(final_df)}')
else:
    print('\nGagal membentuk dataset. Tidak ada data yang valid.')