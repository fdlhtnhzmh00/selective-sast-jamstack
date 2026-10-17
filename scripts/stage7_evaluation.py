import pandas as pd
import os

file_path = os.path.join('data', 'processed', 'final_dataset.csv')

try:
    df = pd.read_csv(file_path)
except FileNotFoundError:
    print("GAGAL: File final_dataset.csv tidak ditemukan.")
    exit()

print("Memproses agregasi data 120k baris menjadi level komit...")

# Agregasi data agar waktu eksekusi tidak terhitung ganda (karena duplikasi merge file vs temuan)
df_commits = df.groupby('commit_hash').agg(
    churn_metric=('absolute_churn', 'max'), 
    scan_time=('median_execution_time_sec', 'max'),
    vuln_count=('rule_id', 'count') 
).reset_index()

# Tiga skenario ambang batas Churn (Threshold)
thresholds = [5, 20, 50] 

print("\n=======================================================")
print("=== HASIL EVALUASI SELECTIVE-SAST BERBASIS CHURN ===")
print("=======================================================\n")

total_commits = len(df_commits)
full_sast_time = df_commits['scan_time'].sum()
full_sast_vulns = df_commits['vuln_count'].sum()

print(f"BASELINE (Metode Full SAST Tradisional):")
print(f"- Total Komit Rentan         : {total_commits}")
print(f"- Total Waktu Komputasi SAST : {full_sast_time:.2f} detik")
print(f"- Total Ground Truth Temuan  : {full_sast_vulns} vulnerabilities\n")

for t in thresholds:
    print(f"--- SKENARIO OPTIMASI (Hanya scan jika absolute_churn > {t}) ---")
    
    # Filter dataset berdasarkan threshold
    selective_df = df_commits[df_commits['churn_metric'] > t]
    skipped_df = df_commits[df_commits['churn_metric'] <= t]

    scanned_commits = len(selective_df)
    selective_time = selective_df['scan_time'].sum()
    selective_vulns = selective_df['vuln_count'].sum()
    missed_vulns = skipped_df['vuln_count'].sum()

    # Kalkulasi Metrik Publikasi
    time_saved_pct = ((full_sast_time - selective_time) / full_sast_time) * 100 if full_sast_time > 0 else 0
    workload_reduction = ((total_commits - scanned_commits) / total_commits) * 100 if total_commits > 0 else 0
    recall = (selective_vulns / full_sast_vulns) * 100 if full_sast_vulns > 0 else 100

    print(f"Komit Dieksekusi CI/CD : {scanned_commits} (Beban antrean dipangkas {workload_reduction:.2f}%)")
    print(f"Waktu Eksekusi Baru    : {selective_time:.2f} detik (Optimasi waktu/Time Saved: {time_saved_pct:.2f}%)")
    print(f"Kerentanan Terdeteksi  : {selective_vulns} (Akurasi/Recall: {recall:.2f}%)")
    print(f"Kerentanan Terlewat    : {missed_vulns} (False Negatives)\n")