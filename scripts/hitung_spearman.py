import pandas as pd
from scipy.stats import spearmanr
df = pd.read_csv('data/processed/final_dataset.csv')
df['has_vuln'] = df['rule_id'].notna().astype(int)

print("RHO RELATIVE:", spearmanr(df['relative_churn_30d'], df['has_vuln'])[0])
print("RHO ENTROPY :", spearmanr(df['entropy_90d'], df['has_vuln'])[0])