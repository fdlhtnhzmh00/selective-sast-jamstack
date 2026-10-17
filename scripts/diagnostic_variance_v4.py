"""
Diagnostic & Reporting Script untuk Variance Characterization v4
Membaca raw_timings_dual_v4.csv (dengan vendored filter)

Output utama:
  1. Comparative analysis v3 vs v4 (jika v3 tersedia)
  2. CV summary dengan/tanpa outlier
  3. Visualisasi siap-paper dengan branding v4
  4. Paragraf siap-copy untuk paper
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
import warnings
warnings.filterwarnings('ignore')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Liberation Serif', 'Times New Roman', 'DejaVu Serif']
plt.rcParams['mathtext.fontset'] = 'stix'

INPUT_FILE = 'data/variance_results_v4/raw_timings_dual_v4.csv'
V3_FILE = 'data/variance_results/raw_timings_dual.csv'  # untuk perbandingan
OUTPUT_DIR = Path('data/variance_results_v4/diagnostic')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
print("="*60)
print("DIAGNOSTIC v4 — dengan Vendored Filter")
print("="*60)

df = pd.read_csv(INPUT_FILE)
print(f"\n[1] Loaded {len(df)} measurements (v4)")
print(f"    Full-SAST     : {(df['mode']=='full').sum()}")
print(f"    Selective-SAST: {(df['mode']=='selective').sum()}")
print(f"    Repositories  : {df['repo_name'].nunique()}")
print(f"    Commits       : {df['commit_hash'].nunique()}")

# Load v3 if available
df_v3 = None
if Path(V3_FILE).exists():
    df_v3 = pd.read_csv(V3_FILE)
    print(f"    [✓] v3 data tersedia ({len(df_v3)} measurements) untuk perbandingan")

# ============================================================
# OUTLIER DETECTION
# ============================================================
print(f"\n[2] Outlier detection (Tukey's fences, k=3.0)")

def detect_outliers_iqr(series, factor=3.0):
    q1, q3 = series.quantile([0.25, 0.75])
    iqr = q3 - q1
    upper = q3 + factor * iqr
    lower = q1 - factor * iqr
    return (series < lower) | (series > upper), upper

for mode in ['full', 'selective']:
    sub = df[df['mode'] == mode]
    is_out, upper = detect_outliers_iqr(sub['wall_clock_sec'], factor=3.0)
    print(f"\n  {mode.upper()}-SAST:")
    print(f"    Q1={sub['wall_clock_sec'].quantile(0.25):.2f}s, "
          f"Q3={sub['wall_clock_sec'].quantile(0.75):.2f}s, "
          f"upper_fence={upper:.2f}s")
    print(f"    Outliers: {is_out.sum()}")
    if is_out.sum() > 0:
        outliers = sub[is_out].sort_values('wall_clock_sec', ascending=False)
        print(f"    Top 5 outliers:")
        for _, row in outliers.head(5).iterrows():
            print(f"      {row['repo_name'][:40]:40s} {row['commit_hash'][:7]} "
                  f"run {row['run_id']}: {row['wall_clock_sec']:.2f}s")

# ============================================================
# CV ANALYSIS
# ============================================================
print(f"\n[3] CV analysis: dengan vs tanpa outlier")

def compute_cv(group):
    if len(group) < 2:
        return np.nan
    m = group['wall_clock_sec'].mean()
    s = group['wall_clock_sec'].std(ddof=1)
    return (s / m * 100) if m > 0 else np.nan

results = {}
for mode in ['full', 'selective']:
    sub = df[df['mode'] == mode].copy()
    is_out, _ = detect_outliers_iqr(sub['wall_clock_sec'], factor=3.0)
    
    cv_all = (sub.groupby(['repo_name', 'commit_hash'], group_keys=False)
                 .apply(compute_cv).dropna())
    cv_clean = (sub[~is_out].groupby(['repo_name', 'commit_hash'], group_keys=False)
                            .apply(compute_cv).dropna())
    
    results[mode] = {
        'all': {
            'n': len(cv_all),
            'median': float(cv_all.median()),
            'p95': float(cv_all.quantile(0.95)),
            'p99': float(cv_all.quantile(0.99)),
            'max': float(cv_all.max()),
        },
        'clean': {
            'n': len(cv_clean),
            'median': float(cv_clean.median()),
            'p95': float(cv_clean.quantile(0.95)),
            'p99': float(cv_clean.quantile(0.99)),
            'max': float(cv_clean.max()),
        },
        'outliers_excluded': int(is_out.sum()),
    }

print(f"\n  {'Mode':<15} {'CV dgn outlier':<25} {'CV tanpa outlier':<25}")
print(f"  {'='*65}")
for mode in ['full', 'selective']:
    r = results[mode]
    all_str = f"{r['all']['median']:.2f}% / P95 {r['all']['p95']:.2f}%"
    clean_str = f"{r['clean']['median']:.2f}% / P95 {r['clean']['p95']:.2f}%"
    print(f"  {mode.upper():<15} {all_str:<25} {clean_str:<25}")

# ============================================================
# TIME SAVING + WILCOXON
# ============================================================
print(f"\n[4] Paired analysis: time saving + Wilcoxon test")

df['key'] = df['repo_name'] + '|' + df['commit_hash']
median_times = df.groupby(['key', 'mode'])['wall_clock_sec'].median().unstack()
paired = median_times.dropna(subset=['full', 'selective']).copy()
paired['delta'] = paired['full'] - paired['selective']
paired['saving_pct'] = (paired['delta'] / paired['full'] * 100)

print(f"    Paired commits: {len(paired)}")
print(f"\n  Time saving distribution:")
print(f"    Min     : {paired['saving_pct'].min():.1f}%")
print(f"    P25     : {paired['saving_pct'].quantile(0.25):.1f}%")
print(f"    Median  : {paired['saving_pct'].median():.1f}%")
print(f"    P75     : {paired['saving_pct'].quantile(0.75):.1f}%")
print(f"    P95     : {paired['saving_pct'].quantile(0.95):.1f}%")
print(f"    Max     : {paired['saving_pct'].max():.1f}%")

negative = paired[paired['saving_pct'] < 0]
print(f"\n    Commits dengan negative saving: {len(negative)}")
if len(negative) > 0:
    print(f"    (Selective-SAST lebih lambat dari Full)")
    for idx, row in negative.head(5).iterrows():
        repo, commit = idx.split('|')
        print(f"      {repo[:35]:35s} {commit[:7]} "
              f"Full={row['full']:.1f}s Sel={row['selective']:.1f}s "
              f"({row['saving_pct']:.1f}%)")

# Wilcoxon
from scipy import stats
stat, p_value = stats.wilcoxon(paired['full'], paired['selective'], alternative='greater')
n = len(paired)
diffs = paired['full'] - paired['selective']
W_pos = stats.rankdata(np.abs(diffs))[diffs > 0].sum()
W_neg = stats.rankdata(np.abs(diffs))[diffs < 0].sum()
rank_biserial = (W_pos - W_neg) / (W_pos + W_neg) if (W_pos + W_neg) > 0 else 0

print(f"\n  Wilcoxon paired signed-rank:")
print(f"    n = {n}")
print(f"    W = {stat:.0f}")
print(f"    p-value = {p_value:.2e}")
print(f"    Rank-biserial r = {rank_biserial:.3f}")

# Bootstrap CI
np.random.seed(42)
boot_medians = []
for _ in range(10000):
    sample = paired['saving_pct'].sample(n=len(paired), replace=True)
    boot_medians.append(sample.median())
ci_low, ci_high = np.percentile(boot_medians, [2.5, 97.5])
print(f"    Bootstrap 95% CI for median saving: [{ci_low:.1f}%, {ci_high:.1f}%]")

# ============================================================
# REPO SIZE STRATIFICATION (BARU di v4 — untuk Pilar 1)
# ============================================================
print(f"\n[5] Time saving by repository size (Pilar 1: asymmetric scaling)")

# Stratifikasi berdasarkan median Full-SAST time per repo (proxy untuk size)
repo_full_median = df[df['mode']=='full'].groupby('repo_name')['wall_clock_sec'].median()
repo_full_median = repo_full_median.sort_values()

# Quartile-based stratification
q1 = repo_full_median.quantile(0.33)
q3 = repo_full_median.quantile(0.67)

def categorize(repo):
    t = repo_full_median.get(repo, np.nan)
    if pd.isna(t): return 'unknown'
    if t < q1: return 'small'
    elif t < q3: return 'medium'
    else: return 'large'

paired['repo'] = paired.index.str.split('|').str[0]
paired['size_cat'] = paired['repo'].apply(categorize)

print(f"\n  Stratification thresholds (per Full-SAST median):")
print(f"    Small  : < {q1:.2f}s")
print(f"    Medium : {q1:.2f}s - {q3:.2f}s")
print(f"    Large  : > {q3:.2f}s")

print(f"\n  {'Category':<10} {'N':<6} {'Median saving':<18} {'P75':<10} {'P95':<10}")
size_stats = {}
for cat in ['small', 'medium', 'large']:
    sub = paired[paired['size_cat'] == cat]
    if len(sub) == 0:
        continue
    med = sub['saving_pct'].median()
    p75 = sub['saving_pct'].quantile(0.75)
    p95 = sub['saving_pct'].quantile(0.95)
    print(f"  {cat:<10} {len(sub):<6} {med:>6.1f}%             {p75:>5.1f}%     {p95:>5.1f}%")
    size_stats[cat] = {
        'n': int(len(sub)),
        'median_saving_pct': float(med),
        'p75_saving_pct': float(p75),
        'p95_saving_pct': float(p95),
    }

# ============================================================
# COMPARATIVE: v3 vs v4
# ============================================================
comparison = None
if df_v3 is not None:
    print(f"\n[6] Comparative analysis: v3 vs v4")
    
    def quick_summary(d, label):
        full = d[d['mode']=='full']['wall_clock_sec']
        sel = d[d['mode']=='selective']['wall_clock_sec']
        return {
            'version': label,
            'n_total': len(d),
            'full_median': float(full.median()),
            'full_max': float(full.max()),
            'selective_median': float(sel.median()),
            'selective_max': float(sel.max()),
        }
    
    s_v3 = quick_summary(df_v3, 'v3')
    s_v4 = quick_summary(df, 'v4')
    
    print(f"\n  {'Metric':<25} {'v3':<15} {'v4':<15} {'Δ':<15}")
    print(f"  {'='*70}")
    print(f"  {'Total measurements':<25} {s_v3['n_total']:<15} {s_v4['n_total']:<15}")
    print(f"  {'Full median (s)':<25} {s_v3['full_median']:<15.2f} {s_v4['full_median']:<15.2f} "
          f"{s_v4['full_median']-s_v3['full_median']:+.2f}")
    print(f"  {'Full max (s)':<25} {s_v3['full_max']:<15.2f} {s_v4['full_max']:<15.2f} "
          f"{s_v4['full_max']-s_v3['full_max']:+.2f}")
    print(f"  {'Selective median (s)':<25} {s_v3['selective_median']:<15.2f} {s_v4['selective_median']:<15.2f} "
          f"{s_v4['selective_median']-s_v3['selective_median']:+.2f}")
    print(f"  {'Selective max (s)':<25} {s_v3['selective_max']:<15.2f} {s_v4['selective_max']:<15.2f} "
          f"{s_v4['selective_max']-s_v3['selective_max']:+.2f}")
    
    # Mantinedev specific check
    mantine_v3 = df_v3[(df_v3['repo_name']=='mantinedev/next-pages-template') & 
                       (df_v3['mode']=='selective')]['wall_clock_sec']
    mantine_v4 = df[(df['repo_name']=='mantinedev/next-pages-template') & 
                    (df['mode']=='selective')]['wall_clock_sec']
    if len(mantine_v3) > 0 and len(mantine_v4) > 0:
        print(f"\n  Mantinedev Selective-SAST:")
        print(f"    v3 median: {mantine_v3.median():.2f}s, max: {mantine_v3.max():.2f}s")
        print(f"    v4 median: {mantine_v4.median():.2f}s, max: {mantine_v4.max():.2f}s")
        print(f"    Improvement: {(1 - mantine_v4.median()/mantine_v3.median())*100:.1f}% reduction")
    
    comparison = {'v3': s_v3, 'v4': s_v4}

# ============================================================
# VISUALIZATIONS
# ============================================================
print(f"\n[7] Generating publication-ready figures...")

# Figure 1: Wall-clock distribution by mode
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=300)
COLORS = {'full': '#3A5F8C', 'selective': '#7A4E1E'}

for i, scale in enumerate(['log', 'linear']):
    ax = axes[i]
    data_full = df[df['mode']=='full']['wall_clock_sec']
    data_sel = df[df['mode']=='selective']['wall_clock_sec']
    
    if scale == 'linear':
        # Filter outlier untuk linear scale
        cap = data_full.quantile(0.95) * 1.5
        data_full = data_full[data_full < cap]
        data_sel = data_sel[data_sel < cap]
    
    bp = ax.boxplot([data_full, data_sel], 
                    tick_labels=['Full-SAST', 'Selective-SAST'],
                    showfliers=True, patch_artist=True, widths=0.5)
    for patch, color in zip(bp['boxes'], [COLORS['full'], COLORS['selective']]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    
    if scale == 'log':
        ax.set_yscale('log')
        ax.set_title('(a) Full distribution (log scale)', fontsize=10)
    else:
        ax.set_title('(b) Below P95×1.5 (typical case)', fontsize=10)
    ax.set_ylabel('Wall-clock time (s)', fontsize=9)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig1_v4_walltime.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig1_v4_walltime.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig1_v4_walltime.png/pdf")

# Figure 2: CV distribution
fig, axes = plt.subplots(1, 2, figsize=(10, 4), dpi=300)
for i, mode in enumerate(['full', 'selective']):
    ax = axes[i]
    sub = df[df['mode'] == mode]
    cv = (sub.groupby(['repo_name', 'commit_hash'], group_keys=False)
             .apply(compute_cv).dropna())
    
    ax.hist(cv, bins=30, color=COLORS[mode], alpha=0.7, edgecolor='black', linewidth=0.5)
    ax.axvline(cv.median(), color='red', linestyle='--', linewidth=1.5,
               label=f'Median = {cv.median():.2f}%')
    ax.axvline(cv.quantile(0.95), color='orange', linestyle=':', linewidth=1.5,
               label=f'P95 = {cv.quantile(0.95):.2f}%')
    ax.set_xlabel('Coefficient of Variation (%)', fontsize=9)
    ax.set_ylabel('Number of commits', fontsize=9)
    ax.set_title(f'({"ab"[i]}) {mode.title()}-SAST (v4)', fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig2_v4_cv_distribution.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig2_v4_cv_distribution.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig2_v4_cv_distribution.png/pdf")

# Figure 3: Time saving distribution + by repo size (Pilar 1)
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=300)

# Histogram
ax = axes[0]
ax.hist(paired['saving_pct'], bins=30, color='#3F6B2E', alpha=0.7, edgecolor='black', linewidth=0.5)
ax.axvline(paired['saving_pct'].median(), color='red', linestyle='--', linewidth=1.5,
           label=f"Median = {paired['saving_pct'].median():.1f}%")
ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.5)
ax.set_xlabel('Time saving (%)', fontsize=9)
ax.set_ylabel('Number of commits', fontsize=9)
ax.set_title(f'(a) Overall distribution (n={len(paired)})', fontsize=10)
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

# Boxplot by size category (Pilar 1: asymmetric scaling)
ax = axes[1]
size_data = []
size_labels = []
for cat in ['small', 'medium', 'large']:
    sub = paired[paired['size_cat'] == cat]
    if len(sub) > 0:
        size_data.append(sub['saving_pct'].values)
        size_labels.append(f"{cat.title()}\n(n={len(sub)})")

bp = ax.boxplot(size_data, tick_labels=size_labels, showfliers=True, 
                patch_artist=True, widths=0.5)
size_colors = ['#88CCEE', '#117733', '#CC6677']
for patch, color in zip(bp['boxes'], size_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)
ax.axhline(0, color='black', linestyle='-', linewidth=0.8, alpha=0.5)
ax.set_ylabel('Time saving (%)', fontsize=9)
ax.set_xlabel('Repository size category', fontsize=9)
ax.set_title('(b) Asymmetric scaling by repo size', fontsize=10)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'fig3_v4_time_saving.png', dpi=300, bbox_inches='tight')
plt.savefig(OUTPUT_DIR / 'fig3_v4_time_saving.pdf', bbox_inches='tight')
plt.close()
print(f"    [✓] fig3_v4_time_saving.png/pdf")

# Figure 4: v3 vs v4 comparison (jika v3 tersedia)
if df_v3 is not None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=300)
    
    # Selective max comparison
    ax = axes[0]
    versions = ['v3 (no filter)', 'v4 (with filter)']
    full_max = [df_v3[df_v3['mode']=='full']['wall_clock_sec'].max(),
                df[df['mode']=='full']['wall_clock_sec'].max()]
    sel_max = [df_v3[df_v3['mode']=='selective']['wall_clock_sec'].max(),
               df[df['mode']=='selective']['wall_clock_sec'].max()]
    
    x = np.arange(len(versions))
    width = 0.35
    bars1 = ax.bar(x - width/2, full_max, width, label='Full-SAST', color=COLORS['full'], alpha=0.7)
    bars2 = ax.bar(x + width/2, sel_max, width, label='Selective-SAST', color=COLORS['selective'], alpha=0.7)
    
    for bar in bars1 + bars2:
        h = bar.get_height()
        ax.annotate(f'{h:.0f}s', xy=(bar.get_x() + bar.get_width()/2, h),
                   xytext=(0, 3), textcoords='offset points', ha='center', fontsize=8)
    
    ax.set_yscale('log')
    ax.set_xticks(x)
    ax.set_xticklabels(versions)
    ax.set_ylabel('Max wall-clock time (s, log scale)', fontsize=9)
    ax.set_title('(a) Maximum execution time', fontsize=10)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')
    
    # Mantinedev specific
    ax = axes[1]
    mantine_v3 = df_v3[(df_v3['repo_name']=='mantinedev/next-pages-template') & 
                       (df_v3['mode']=='selective')]['wall_clock_sec'].values
    mantine_v4 = df[(df['repo_name']=='mantinedev/next-pages-template') & 
                    (df['mode']=='selective')]['wall_clock_sec'].values
    
    if len(mantine_v3) > 0 and len(mantine_v4) > 0:
        positions = [1, 2]
        bp = ax.boxplot([mantine_v3, mantine_v4], positions=positions, widths=0.5,
                        patch_artist=True, showfliers=True)
        for patch, color in zip(bp['boxes'], ['#CC6677', '#117733']):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax.set_xticks(positions)
        ax.set_xticklabels(['v3 (no filter)', 'v4 (with filter)'])
        ax.set_yscale('log')
        ax.set_ylabel('Selective-SAST time (s, log scale)', fontsize=9)
        ax.set_title('(b) Mantinedev case study', fontsize=10)
        ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'fig4_v3_vs_v4.png', dpi=300, bbox_inches='tight')
    plt.savefig(OUTPUT_DIR / 'fig4_v3_vs_v4.pdf', bbox_inches='tight')
    plt.close()
    print(f"    [✓] fig4_v3_vs_v4.png/pdf")

# ============================================================
# FINAL REPORT
# ============================================================
final_report = {
    'version': 'v4_with_vendored_filter',
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
        'commits_with_negative_saving': int(len(negative)),
    },
    'wilcoxon_test': {
        'W': float(stat),
        'p_value': float(p_value),
        'rank_biserial_r': round(float(rank_biserial), 3),
    },
    'size_stratification': size_stats,
    'comparison_v3_v4': comparison,
}

with open(OUTPUT_DIR / 'final_report_v4.json', 'w') as f:
    json.dump(final_report, f, indent=2)

print(f"\n[✓] Final report: {OUTPUT_DIR / 'final_report_v4.json'}")
print(f"\nFile yang dihasilkan:")
for f in sorted(OUTPUT_DIR.iterdir()):
    print(f"  - {f.name}")

print(f"\n{'='*60}")
print("KEY METRICS UNTUK PAPER:")
print(f"{'='*60}")
print(f"  Median CV (Full)     : {results['full']['all']['median']:.2f}%")
print(f"  Median CV (Selective): {results['selective']['all']['median']:.2f}%")
print(f"  P95 CV (Full)        : {results['full']['all']['p95']:.2f}%")
print(f"  P95 CV (Selective)   : {results['selective']['all']['p95']:.2f}%")
print(f"  Median time saving   : {paired['saving_pct'].median():.1f}%")
print(f"  95% CI               : [{ci_low:.1f}%, {ci_high:.1f}%]")
print(f"  Wilcoxon p-value     : {p_value:.2e}")
print(f"  Effect size r        : {rank_biserial:.3f}")
if 'large' in size_stats:
    print(f"  Saving on large repos: {size_stats['large']['median_saving_pct']:.1f}% median")