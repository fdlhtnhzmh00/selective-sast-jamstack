import pandas as pd
df = pd.read_csv('data/processed/final_dataset.csv')

# Buang nilai dummy 999.0 untuk melihat distribusi file yang benar-benar pernah dimodifikasi
df_clean = df[df['days_since_last_mod'] < 999]
p80_asli = df_clean['days_since_last_mod'].quantile(0.80)

print(f"P80 ASLI (Tanpa file baru): {p80_asli:.1f} hari")