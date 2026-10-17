import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# -----------------------------
# 0. Load Dataset
# -----------------------------
df = pd.read_csv('/home/tecno/projects/selective-sast-jamstack/data/processed/final_dataset_patched.csv')

# -----------------------------
# 1. Siapkan data
# -----------------------------
df_churn = df.drop_duplicates(subset=[
    "repo_name_x",
    "commit_hash",
    "file_path_at_commit",
    "lines_added",
    "lines_deleted",
    "absolute_churn",
    "relative_churn_30d",
    "entropy_90d",
    "days_since_last_mod"
]).copy()

df_churn["log_absolute_churn"] = np.log10(df_churn["absolute_churn"] + 1)

# -----------------------------
# 2. Atur font global
# -----------------------------
plt.rcParams["font.family"] = "Carlito"
plt.rcParams["axes.titlesize"] = 16
plt.rcParams["axes.labelsize"] = 12
plt.rcParams["xtick.labelsize"] = 11
plt.rcParams["ytick.labelsize"] = 11

# -----------------------------
# 3. Fungsi untuk membuat grafik
# -----------------------------
def plot_churn_distribution(data, title, xlabel, ylabel, output_file):
    plt.figure(figsize=(7, 4))
    plt.hist(data["log_absolute_churn"], bins=40, edgecolor="black")
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    plt.close()

# -----------------------------
# 4. Versi Bahasa Indonesia
# -----------------------------
plot_churn_distribution(
    data=df_churn,
    title="Distribusi Code Churn",
    xlabel="log10(Absolute Churn + 1)",
    ylabel="Jumlah perubahan file-commit",
    output_file="gambar_2_distribusi_code_churn_id.png"
)

# -----------------------------
# 5. Versi Bahasa Inggris
# -----------------------------
plot_churn_distribution(
    data=df_churn,
    title="Code Churn Distribution",
    xlabel="log10(Absolute Churn + 1)",
    ylabel="Number of file-commit changes",
    output_file="figure_2_code_churn_distribution_en.png"
)

print("Selesai. Dua gambar berhasil disimpan.")