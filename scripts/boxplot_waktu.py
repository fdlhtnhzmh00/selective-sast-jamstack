import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------
# 1. Atur Font (Times New Roman)
# -----------------------------
plt.rcParams["font.family"] = "Times New Roman"
plt.rcParams["axes.titlesize"] = 14
plt.rcParams["axes.labelsize"] = 12
plt.rcParams["xtick.labelsize"] = 11
plt.rcParams["ytick.labelsize"] = 11

# -----------------------------
# 2. Path Akurat ke File Dataset
# -----------------------------
file_path = "/home/tecno/projects/selective-sast-jamstack/data/variance_results_v4_patched/raw_timings_dual_v4_patched.csv"

# -----------------------------
# -----------------------------
# 3. Proses Data
# -----------------------------
df_time = pd.read_csv(file_path)
df_time = df_time[df_time["returncode"] == 0].copy()

# --- FILTER 6 BULAN (TAMBAHAN BARU) ---
# Pastikan path ini menunjuk ke dataset 6 bulan yang baru saja kamu buat
path_6mo = "/home/tecno/projects/selective-sast-jamstack/data/processed/final_dataset_6mo.csv" 
df_6mo = pd.read_csv(path_6mo)

# Ambil daftar commit yang lolos filter 6 bulan
valid_commits = df_6mo['commit_hash'].unique()

# Pangkas data waktu eksekusi agar hanya menyisakan commit 6 bulan terakhir
df_time = df_time[df_time['commit_hash'].isin(valid_commits)]
# --------------------------------------

df_runtime = df_time.groupby(["repo_name", "commit_hash", "mode"])["wall_clock_sec"].median().reset_index()
df_paired = df_runtime.pivot_table(index=["repo_name", "commit_hash"], columns="mode", values="wall_clock_sec").reset_index()
df_paired = df_paired.dropna(subset=["full", "selective"])

# -----------------------------
# 4. Fungsi Plotting Standar Jurnal
# -----------------------------
def plot_execution_time(df, title_a, title_b, ylabel_a, ylabel_b, labels, output_filename):
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))
    data_full = df["full"].dropna()
    data_sel = df["selective"].dropna()
    
    # Warna pastel standar akademik
    colors = ['#8CA1B6', '#A1917B'] 

    # Subplot 1: Skala Logaritmik (Outlier)
    bplot1 = axes[0].boxplot([data_full, data_sel], labels=labels, patch_artist=True, medianprops=dict(color="orange", linewidth=2))
    for patch, color in zip(bplot1['boxes'], colors):
        patch.set_facecolor(color)
    axes[0].set_yscale("log")
    axes[0].set_title(title_a)
    axes[0].set_ylabel(ylabel_a)
    axes[0].grid(True, alpha=0.3)

    # Subplot 2: Kasus Tipikal (P95)
    p95_max = max(data_full.quantile(0.95), data_sel.quantile(0.95))
    bplot2 = axes[1].boxplot([data_full, data_sel], labels=labels, patch_artist=True, medianprops=dict(color="orange", linewidth=2))
    for patch, color in zip(bplot2['boxes'], colors):
        patch.set_facecolor(color)
    axes[1].set_ylim(bottom=min(data_full.min(), data_sel.min()) * 0.9, top=p95_max * 1.05)
    axes[1].set_title(title_b)
    axes[1].set_ylabel(ylabel_b)
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_filename, dpi=300, bbox_inches="tight")
    plt.close()

# -----------------------------
# 5. Generate Gambar ID & EN
# -----------------------------
plot_execution_time(
    df=df_paired,
    title_a="(a) Dengan pencilan (skala log)",
    title_b="(b) Di bawah persentil ke-95 (kasus tipikal)",
    ylabel_a="Waktu eksekusi (detik, skala log)",
    ylabel_b="Waktu eksekusi (detik)",
    labels=["Full-SAST", "Selective-SAST"],
    output_filename="gambar_3_perbandingan_waktu_id.png"
)

plot_execution_time(
    df=df_paired,
    title_a="(a) With outliers (log scale)",
    title_b="(b) Below P95 (typical case)",
    ylabel_a="Wall-clock time (s, log scale)",
    ylabel_b="Wall-clock time (s)",
    labels=["Full-SAST", "Selective-SAST"],
    output_filename="figure_3_execution_time_comparison_en.png"
)

print("Selesai. Dua gambar berhasil disimpan.")
