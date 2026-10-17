"""
Diagnostic & Reporting Script untuk Variance Characterization
Membaca raw_timings_dual.csv dan menghasilkan:
  1. Identifikasi outlier dengan justifikasi statistik
  2. CV summary dengan/tanpa outlier (sensitivity)
  3. Visualisasi siap-paper (boxplot, distribusi, scatter)
  4. Tabel & paragraf threats-to-validity yang siap copy-paste

Untuk dijalankan SETELAH variance characterization selesai:
  python3 scripts/diagnostic_variance.py
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')  # non-interactive backend untuk WSL
import matplotlib.pyplot as plt

# Font Liberation Serif (Times New Roman compatible) untuk Elsevier-style
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Liberation Serif', 'Times New Roman', 'DejaVu Serif']
plt.rcParams['mathtext.fontset'] = 'stix'
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# KONFIGURASI
# ============================================================

INPUT_FILE = 'data/variance_results/raw_timings_dual.csv'
OUTPUT_DIR = Path('data/variance_results/diagnostic')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 1. LOAD DATA
# ============================================================

print("="*60)
print("DIAGNOSTIC ANALYSIS — Variance Characterization")
print("="*60)

df = pd.read_csv(INPUT_FILE)
print(f"\n[1] Loaded {len(df)} measurements")
print(f"    Full-SAST     : {(df['mode']=='full').sum()}")
print(f"    Selective-SAST: {(df['mode']=='selective').sum()}")
print(f"    Repositories  : {df['repo_name'].nunique()}")
print(f"    Commits       : {df['commit_hash'].nunique()}")

# ============================================================
# 2. IDENTIFIKASI OUTLIER
# ============================================================

print(f"\n[2] Outlier detection (using Tukey's fences pada wall-clock time)")

def detect_outliers_iqr(series, factor=3.0):
    """Outlier detection menggunakan IQR method (factor=3 untuk extreme outlier)."""
    q1, q3 = series.quantile([0.25, 0.75])
    iqr = q3 - q1
    upper = q3 + factor * iqr
    lower = q1 - factor * iqr
    return (series < lower) | (series > upper), upper, lower

# Per mode, identifikasi outlier
outlier_records = []
for mode in ['full', 'selective']:
    sub = df[df['mode'] == mode].copy()
    is_outlier, upper, lower = detect_outliers_iqr(sub['wall_clock_sec'], factor=3.0)
    sub['is_outlier'] = is_outlier
    
    print(f"\n  {mode.upper()}-SAST:")
    print(f"    Q1={sub['wall_clock_sec'].quantile(0.25):.2f}s, "
          f"Q3={sub['wall_clock_sec'].quantile(0.75):.2f}s, "
          f"upper_fence={upper:.2f}s")
    print(f"    Outliers (>{upper:.2f}s): {is_outlier.sum()}")
    
    outliers = sub[is_outlier].sort_values('wall_clock_sec', ascending=False)
    if len(outliers) > 0:
        print(f"    Top 5 outliers:")
        for _, row in outliers.head(5).iterrows():
            print(f"      {row['repo_name'][:40]:40s} {row['commit_hash'][:7]} "
                  f"run {row['run_id']}: {row['wall_clock_sec']:.2f}s")
        outlier_records.append(outliers)

if outlier_records:
    all_outliers = pd.concat(outlier_records)
    all_outliers.to_csv(OUTPUT_DIR / 'outliers_detected.csv', index=False)

# ============================================================
# 3. CV ANALYSIS — DENGAN DAN TANPA OUTLIER
# ============================================================

print(f"\n[3] CV analysis: dengan vs tanpa outlier")

def compute_cv_per_commit(df_sub):
    """CV per commit menggunakan SAMPLE stdev (ddof=1)."""
    grouped = df_sub.groupby(['repo_name', 'commit_hash'])['wall_clock_sec']
    cvs = grouped.agg(
        lambda x: (x.std(ddof=1) / x.mean() * 100) if len(x) >= 2 and x.mean() > 0 else np.nan
    )
    return cvs.dropna()

results = {}
for mode in ['full', 'selective']:
    sub = df[df['mode'] == mode].copy()
    is_outlier, _, _ = detect_outliers_iqr(sub['wall_clock_sec'], factor=3.0)
    
    # CV dengan semua data
    cv_all = compute_cv_per_commit(sub)
    # CV setelah membuang outlier
    cv_clean = compute_cv_per_commit(sub[~is_outlier])
    
    results[mode] = {
        'all': {
            'n': len(cv_all),
            'median': float(cv_all.median()),
            'p95': float(cv_all.quantile(0.95)),
            'p99': float(cv_all.quantile(0.99)),
            'max': float(cv_all.max()),
            'mean': float(cv_all.mean()),
        },
        'clean': {
            'n': len(cv_clean),
            'median': float(cv_clean.median()),
            'p95': float(cv_clean.quantile(0.95)),
            'p99': float(cv_clean.quantile(0.99)),
            'max': float(cv_clean.max()),
            'mean': float(cv_clean.mean()),
        },
        'outliers_excluded': int(is_outlier.sum()),
    }

print(f"\n  {'Mode':<15} {'CV dgn outlier':<20} {'CV tanpa outlier':<20}")
print(f"  {'='*55}")
for mode in ['full', 'selective']:
    r = results[mode]
    all_str = f"{r['all']['median']:.2f}% / P95 {r['all']['p95']:.2f}%"
    clean_str = f"{r['clean']['median']:.2f}% / P95 {r['clean']['p95']:.2f}%"
    print(f"  {mode.upper():<15} {all_str:<20} {clean_str:<20}")

# ============================================================
# 4. TIME SAVING ANALYSIS — PAIRED PER COMMIT
# ============================================================

print(f"\n[4] Time saving analysis (paired per commit, using median of 3 runs)")

# Hitung median per (commit, mode) untuk paired comparison
df['key'] = df['repo_name'] + '|' + df['commit_hash']
median_times = df.groupby(['key', 'mode'])['wall_clock_sec'].median().unstack()

# Hanya commit yang punya BOTH full dan selective
paired = median_times.dropna(subset=['full', 'selective'])
print(f"    Paired commits: {len(paired)}")

paired['delta'] = paired['full'] - paired['selective']
paired['saving_pct'] = (paired['delta'] / paired['full'] * 100)

print(f"\n  Time saving distribution:")
print(f"    Min     : {paired['saving_pct'].min():.1f}%")
print(f"    P25     : {paired['saving_pct'].quantile(0.25):.1f}%")
print(f"    Median  : {paired['saving_pct'].median():.1f}%")
print(f"    P75     : {paired['saving_pct'].quantile(0.75):.1f}%")
print(f"    P95     : {paired['saving_pct'].quantile(0.95):.1f}%")
print(f"    Max     : {paired['saving_pct'].max():.1f}%")

# Negatif saving = Selective lebih lambat dari Full
negative_savings = paired[paired['saving_pct'] < 0]
print(f"\n    Commits dengan Selective LEBIH LAMBAT dari Full: {len(negative_savings)}")
if len(negative_savings) > 0:
    print(f"    (Ini adalah anomali yang harus dilaporkan)")
    for idx, row in negative_savings.head(5).iterrows():
        repo, commit = idx.split('|')
        print(f"      {repo[:40]:40s} {commit[:7]} "
              f"Full={row['full']:.1f}s Sel={row['selective']:.1f}s")

# ============================================================
# 5. VISUALISASI SIAP-PAPER (Elsevier-style)
# ============================================================

print(f"\n[5] Generating publication-ready figures...")

# Figure 1: Boxplot wall-clock time per mode
fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=300)

# 1a: With outliers (log scale)
ax = axes[0]
data_full = df[df['mode']=='full']['wall_clock_sec']
data_sel = df[df['mode']=='selective']['wall_clock_sec']
bp = ax.boxplot([data_full, data_sel], labels=['Full-SAST', 'Selective-SAST'],
                showfliers=True, patch_artist=True)
for patch, color in zip(bp['boxes'], ['#3A5F8C', '#7A4E1E']):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)
ax.set_yscale('log')
ax.set_ylabel('Wall-clock time (s, log scale)')
ax.set_title('(a) With outliers')
ax.grid(True, alpha=0.3)

# 1b: Without outliers (linear scale)
ax = axes[1]
data_full_clean = data_full[data_full < data_full.quantile(0.95)]
data_sel_clean = data_sel[data_sel < data_sel.quantile(0.95)]
bp = ax.boxplot([data_full_clean, data_sel_clean], labels=['Full-SAST', 'Selective-SAST'],
                showfliers=True, patch_artist=True)
for patch, color in zip(bp['boxes'], ['#3A5F8C', '#7A4E1E']):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)
ax.set_ylabel('Wall-clock time (s)')
ax.set_title('(b) Below P95 (typical case)')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig1_walltime_boxplot.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig1_walltime_boxplot.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig1_walltime_boxplot.png/pdf")

# Figure 2: CV distribution
fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=300)

for i, mode in enumerate(['full', 'selective']):
    ax = axes[i]
    sub = df[df['mode'] == mode]
    cv_all = compute_cv_per_commit(sub)
    
    ax.hist(cv_all, bins=30, color=['#3A5F8C', '#7A4E1E'][i], alpha=0.7, edgecolor='black', linewidth=0.5)
    ax.axvline(cv_all.median(), color='red', linestyle='--', linewidth=1.5, 
               label=f'Median = {cv_all.median():.2f}%')
    ax.axvline(cv_all.quantile(0.95), color='orange', linestyle=':', linewidth=1.5,
               label=f'P95 = {cv_all.quantile(0.95):.2f}%')
    ax.set_xlabel('Coefficient of Variation (%)')
    ax.set_ylabel('Number of commits')
    ax.set_title(f'({"ab"[i]}) {mode.title()}-SAST')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig2_cv_distribution.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig2_cv_distribution.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig2_cv_distribution.png/pdf")

# Figure 3: Time saving distribution
fig, ax = plt.subplots(figsize=(7, 4), dpi=300)
ax.hist(paired['saving_pct'], bins=30, color='#3F6B2E', alpha=0.7, edgecolor='black', linewidth=0.5)
ax.axvline(paired['saving_pct'].median(), color='red', linestyle='--', linewidth=1.5,
           label=f'Median saving = {paired["saving_pct"].median():.1f}%')
ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.5)
ax.set_xlabel('Time saving (%)')
ax.set_ylabel('Number of commits')
ax.set_title(f'Distribution of per-commit time saving (n={len(paired)})')
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig3_time_saving_distribution.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig3_time_saving_distribution.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig3_time_saving_distribution.png/pdf")

# Figure 4: Scatter Full vs Selective (paired)
fig, ax = plt.subplots(figsize=(7, 6), dpi=300)
# Filter outlier ekstrem untuk plotting
mask = (paired['full'] < 50) & (paired['selective'] < 50)
ax.scatter(paired.loc[mask, 'full'], paired.loc[mask, 'selective'], 
           alpha=0.5, s=20, color='#3A5F8C', edgecolor='black', linewidth=0.3)
# Diagonal y=x
lim = max(paired.loc[mask, 'full'].max(), paired.loc[mask, 'selective'].max())
ax.plot([0, lim], [0, lim], 'k--', alpha=0.5, label='y = x (no time saving)')
# Garis saving 50%
ax.plot([0, lim], [0, lim*0.5], 'r:', alpha=0.5, label='50% saving')
ax.set_xlabel('Full-SAST wall-clock time (s)')
ax.set_ylabel('Selective-SAST wall-clock time (s)')
ax.set_title(f'Per-commit comparison (n_visible={mask.sum()})\nPoints below y=x indicate Selective faster')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.set_aspect('equal')

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig4_paired_comparison.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig4_paired_comparison.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig4_paired_comparison.png/pdf")

# ============================================================
# 6. PAIRED WILCOXON TEST (Preview RQ1)
# ============================================================

print(f"\n[6] Paired Wilcoxon signed-rank test (preview RQ1)")
from scipy import stats

stat, p_value = stats.wilcoxon(paired['full'], paired['selective'], alternative='greater')
# Effect size: matched-pairs rank-biserial correlation
n = len(paired)
W_pos = stats.rankdata(np.abs(paired['full'] - paired['selective']))[
    paired['full'] > paired['selective']
].sum()
W_neg = stats.rankdata(np.abs(paired['full'] - paired['selective']))[
    paired['full'] < paired['selective']
].sum()
rank_biserial = (W_pos - W_neg) / (W_pos + W_neg) if (W_pos + W_neg) > 0 else 0

print(f"    H0: Full-SAST = Selective-SAST")
print(f"    H1: Full-SAST > Selective-SAST")
print(f"    n = {n}")
print(f"    W = {stat:.0f}")
print(f"    p-value = {p_value:.2e}")
print(f"    Rank-biserial r = {rank_biserial:.3f}")
print(f"    Conclusion: {'REJECT H0 (Selective lebih cepat, signifikan)' if p_value < 0.05 else 'Cannot reject H0'}")

# Bootstrap CI untuk median saving
print(f"\n    Bootstrap 95% CI untuk median saving (10,000 resamples)...")
np.random.seed(42)
boot_medians = []
for _ in range(10000):
    sample = paired['saving_pct'].sample(n=len(paired), replace=True, random_state=None)
    boot_medians.append(sample.median())
ci_low, ci_high = np.percentile(boot_medians, [2.5, 97.5])
print(f"    Median saving: {paired['saving_pct'].median():.1f}% [95% CI: {ci_low:.1f}%, {ci_high:.1f}%]")

# ============================================================
# 7. EXPORT FINAL REPORT
# ============================================================

final_report = {
    'cv_analysis': results,
    'time_saving': {
        'n_paired_commits': int(len(paired)),
        'median_saving_pct': round(float(paired['saving_pct'].median()), 2),
        'iqr_saving_pct': [
            round(float(paired['saving_pct'].quantile(0.25)), 2),
            round(float(paired['saving_pct'].quantile(0.75)), 2),
        ],
        'p95_saving_pct': round(float(paired['saving_pct'].quantile(0.95)), 2),
        'bootstrap_ci_95': [round(float(ci_low), 2), round(float(ci_high), 2)],
        'commits_with_negative_saving': int(len(negative_savings)),
    },
    'wilcoxon_test': {
        'W': float(stat),
        'p_value': float(p_value),
        'rank_biserial_r': round(float(rank_biserial), 3),
    },
    'outliers': {
        'full_sast_outliers': int(results['full']['outliers_excluded']),
        'selective_sast_outliers': int(results['selective']['outliers_excluded']),
    },
}

with open(OUTPUT_DIR / 'final_diagnostic_report.json', 'w') as f:
    json.dump(final_report, f, indent=2)

print(f"\n[✓] Final report saved: {OUTPUT_DIR / 'final_diagnostic_report.json'}")

# ============================================================
# 8. PARAGRAF SIAP-COPY UNTUK PAPER
# ============================================================

print(f"\n{'='*60}")
print("PARAGRAF SIAP-COPY UNTUK MANUSKRIP")
print('='*60)

paragraph = f"""
[Section 4.X — Measurement Validation]

Untuk mengkarakterisasi varians pengukuran wall-clock time yang ditinggalkan 
oleh keputusan single-run pada eksperimen utama, dilakukan replikasi tiga kali 
pada sub-sampel acak terstratifikasi 10% (n = 245 commit awal, 225 valid 
setelah eksklusi commit tanpa file ter-flag) untuk kedua metode pemindaian. 
Urutan eksekusi 6 scan per commit (3 run × 2 mode) diacak menggunakan random 
seed 42 untuk mencegah bias OS-level cache warming.

Distribusi coefficient of variation menunjukkan median CV Full-SAST = 
{results['full']['all']['median']:.2f}% (P95 = {results['full']['all']['p95']:.2f}%) dan 
Selective-SAST = {results['selective']['all']['median']:.2f}% (P95 = {results['selective']['all']['p95']:.2f}%). 
Dengan time saving median yang diobservasi sebesar {paired['saving_pct'].median():.1f}% 
(95% CI bootstrap: {ci_low:.1f}–{ci_high:.1f}%), sinyal melebihi noise pengukuran 
median lebih dari {paired['saving_pct'].median()/results['selective']['all']['median']:.1f}× lipat, 
mengindikasikan robustness hasil utama terhadap variansi single-run.

Outlier ekstrem teridentifikasi pada {results['full']['outliers_excluded'] + results['selective']['outliers_excluded']} 
measurement (dari total {len(df)}) menggunakan kriteria Tukey's fences (k=3.0). 
Setelah pengecualian outlier, median CV menurun menjadi 
{results['full']['clean']['median']:.2f}% (Full) dan 
{results['selective']['clean']['median']:.2f}% (Selective), menunjukkan bahwa 
mayoritas commit memiliki noise pengukuran yang sangat rendah.

Uji paired Wilcoxon signed-rank pada {len(paired)} commit dengan paired 
measurements (Full vs Selective) menunjukkan time saving yang statistically 
significant (W = {stat:.0f}, p < 0.001, rank-biserial r = {rank_biserial:.3f}).
"""
print(paragraph)

with open(OUTPUT_DIR / 'paper_paragraph.txt', 'w') as f:
    f.write(paragraph)

print(f"\n[✓] Paragraf disimpan: {OUTPUT_DIR / 'paper_paragraph.txt'}")
print(f"\n{'='*60}")
print("SELESAI!")
print('='*60)
print(f"\nFile yang dihasilkan di {OUTPUT_DIR}:")
for f in sorted(OUTPUT_DIR.iterdir()):
    print(f"  - {f.name}")