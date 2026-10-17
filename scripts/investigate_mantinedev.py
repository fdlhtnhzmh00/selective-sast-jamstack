"""
Investigasi anomali: mantinedev/next-pages-template

Tujuan: Memahami mengapa Selective-SAST membutuhkan 1300+ detik
        sementara Full-SAST hanya 7.5 detik pada repo yang sama.

Hipotesis yang akan diuji:
1. File spesifik yang menyebabkan pathological matching
2. Konfigurasi rule Semgrep yang triggering exponential complexity
3. Bug di path resolution skrip variance

Pendekatan:
- Re-clone repo ke commit yang dimaksud
- Identifikasi 3 file yang ter-flag dari dataset
- Scan masing-masing file SECARA INDIVIDUAL untuk mengisolasi penyebab
- Coba scan dengan rule subset untuk identifikasi rule pelanggar
"""

import os
import subprocess
import time
import shutil
import pandas as pd
from pathlib import Path

REPO_URL = 'https://github.com/mantinedev/next-pages-template.git'
REPO_NAME = 'mantinedev_next-pages-template_investigation'
TARGET_COMMIT = 'aa8264c'  # commit yang anomali
WORK_DIR = Path('/tmp/sast_investigation')
WORK_DIR.mkdir(exist_ok=True)
REPO_PATH = WORK_DIR / REPO_NAME

# Load dataset untuk identifikasi file ter-flag
print("="*70)
print("INVESTIGASI: mantinedev/next-pages-template @ aa8264c")
print("="*70)

print("\n[1] Membaca dataset untuk identifikasi file ter-flag...")
df = pd.read_csv('data/processed/final_dataset.csv')
target = df[
    (df['repo_name_x'] == 'mantinedev/next-pages-template') &
    (df['commit_hash'].str.startswith(TARGET_COMMIT))
]

if len(target) == 0:
    print(f"[!] Commit {TARGET_COMMIT} tidak ditemukan untuk Mantinedev di dataset")
    exit(1)

print(f"    Total file dimodifikasi: {len(target)}")

# Hitung threshold churn p75 untuk repo
churn_p75 = df[df['repo_name_x'] == 'mantinedev/next-pages-template']['relative_churn_30d'].quantile(0.75)
print(f"    Churn p75 (repo)        : {churn_p75:.4f}")

# Identifikasi file ter-flag
flagged = target[
    (target['relative_churn_30d'] > churn_p75) |
    (target['entropy_90d'] > 1.5) |
    (target['touches_config'] | target['touches_auth'] | target['touches_api'] | target['touches_ci']) |
    (target['days_since_last_mod'] > 14)
]
print(f"    File ter-flag           : {len(flagged)}")

flagged_files = flagged['file_path_at_commit'].str.replace('\\', '/').unique().tolist()
print(f"\n[2] File yang ter-flag (akan diinvestigasi):")
for f in flagged_files:
    # Tampilkan info file
    file_info = flagged[flagged['file_path_at_commit'].str.replace('\\', '/') == f].iloc[0]
    print(f"    - {f}")
    print(f"      churn: {file_info['relative_churn_30d']:.4f}, "
          f"entropy: {file_info['entropy_90d']:.2f}, "
          f"staleness: {file_info['days_since_last_mod']:.0f}d")

# Clone repo
print(f"\n[3] Cloning {REPO_URL}...")
shutil.rmtree(REPO_PATH, ignore_errors=True)
subprocess.run(['git', 'clone', '--quiet', REPO_URL, str(REPO_PATH)], check=True)

# Find full commit hash
result = subprocess.run(
    ['git', 'log', '--all', '--format=%H', '--abbrev-commit'],
    cwd=REPO_PATH, capture_output=True, text=True
)
full_hash = None
for line in result.stdout.split('\n'):
    if line.startswith(TARGET_COMMIT):
        full_hash = line.strip()
        break

if not full_hash:
    print(f"[!] Commit {TARGET_COMMIT} tidak ditemukan di repo")
    exit(1)

print(f"    Full hash: {full_hash}")

# Checkout
subprocess.run(['git', 'checkout', '-f', '--quiet', full_hash], cwd=REPO_PATH, check=True)

# Verifikasi file ada
print(f"\n[4] Verifikasi file ter-flag exist:")
existing = []
for f in flagged_files:
    full_path = REPO_PATH / f
    exists = full_path.exists()
    status = "✓" if exists else "✗"
    if exists:
        size = full_path.stat().st_size
        line_count = sum(1 for _ in open(full_path, 'rb'))
        print(f"    {status} {f} ({size:,} bytes, {line_count} lines)")
        existing.append(f)
    else:
        print(f"    {status} {f} (NOT FOUND)")

if not existing:
    print("[!] Tidak ada file yang valid untuk di-scan")
    exit(1)

# ============================================================
# TEST 1: Scan setiap file secara TERPISAH dengan ruleset penuh
# ============================================================
print(f"\n[5] TEST 1: Scan masing-masing file dengan ruleset penuh")
print(f"    Tujuan: Identifikasi file mana yang menyebabkan slowdown")

SEMGREP_FULL = [
    '--config=p/javascript', '--config=p/typescript',
    '--config=p/react', '--config=p/nextjs',
    '--config=p/security-audit', '--config=p/owasp-top-ten',
    '--config=p/jwt',
]

per_file_timings = []
for f in existing:
    print(f"\n    Scanning {f}...")
    cmd = ['semgrep', 'scan', *SEMGREP_FULL,
           '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
           '--timeout=300', f]
    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, cwd=REPO_PATH,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE,
                              timeout=600)
        elapsed = time.perf_counter() - start
        print(f"      Time: {elapsed:.2f}s (returncode={result.returncode})")
        per_file_timings.append((f, elapsed, result.returncode))
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - start
        print(f"      TIMEOUT setelah {elapsed:.2f}s")
        per_file_timings.append((f, elapsed, -1))

# ============================================================
# TEST 2: Scan SEMUA file bersama dengan ruleset penuh (replikasi anomali)
# ============================================================
print(f"\n[6] TEST 2: Scan ALL file together (replikasi anomali variance)")
print(f"    Cmd: semgrep ... {' '.join(existing)}")
cmd = ['semgrep', 'scan', *SEMGREP_FULL,
       '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
       '--timeout=300', *existing]
start = time.perf_counter()
try:
    result = subprocess.run(cmd, cwd=REPO_PATH,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,
                          timeout=1800)
    elapsed = time.perf_counter() - start
    print(f"    Time: {elapsed:.2f}s")
except subprocess.TimeoutExpired:
    elapsed = time.perf_counter() - start
    print(f"    TIMEOUT setelah {elapsed:.2f}s")

# ============================================================
# TEST 3: Scan SELURUH repository (untuk perbandingan dengan Full-SAST)
# ============================================================
print(f"\n[7] TEST 3: Scan SELURUH repo (Full-SAST untuk perbandingan)")
cmd = ['semgrep', 'scan', *SEMGREP_FULL,
       '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
       '--timeout=300', '.']
start = time.perf_counter()
try:
    result = subprocess.run(cmd, cwd=REPO_PATH,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE,
                          timeout=1800)
    elapsed = time.perf_counter() - start
    print(f"    Time: {elapsed:.2f}s")
except subprocess.TimeoutExpired:
    elapsed = time.perf_counter() - start
    print(f"    TIMEOUT setelah {elapsed:.2f}s")

# ============================================================
# TEST 4: Scan dengan ruleset MINIMAL untuk isolate rule problem
# ============================================================
print(f"\n[8] TEST 4: Scan dengan ruleset minimal (untuk isolate rule pelanggar)")
for ruleset_name, ruleset in [
    ('p/javascript', ['--config=p/javascript']),
    ('p/typescript', ['--config=p/typescript']),
    ('p/react', ['--config=p/react']),
    ('p/nextjs', ['--config=p/nextjs']),
    ('p/security-audit', ['--config=p/security-audit']),
    ('p/owasp-top-ten', ['--config=p/owasp-top-ten']),
    ('p/jwt', ['--config=p/jwt']),
]:
    cmd = ['semgrep', 'scan', *ruleset,
           '--metrics=off', '--no-rewrite-rule-ids', '--quiet',
           '--timeout=120', *existing]
    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, cwd=REPO_PATH,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE,
                              timeout=600)
        elapsed = time.perf_counter() - start
        flag = " ⚠️ SLOW!" if elapsed > 30 else ""
        print(f"    {ruleset_name:25s}: {elapsed:7.2f}s{flag}")
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - start
        print(f"    {ruleset_name:25s}: TIMEOUT ({elapsed:.2f}s) ⚠️ PATHOLOGICAL")

# ============================================================
# RANGKUMAN & DIAGNOSIS
# ============================================================
print(f"\n{'='*70}")
print("DIAGNOSIS")
print('='*70)
print(f"""
Hasil investigasi akan mengindikasikan:

a) Jika TEST 1 menunjukkan 1 file lambat → file tersebut adalah penyebabnya.
   Lihat isi file untuk identifikasi pattern problematic.

b) Jika TEST 1 cepat tapi TEST 2 lambat → masalah pada interaksi multi-file.
   Mungkin shared analysis context atau cross-file analysis.

c) Jika TEST 4 menunjukkan 1 ruleset yang lambat → ruleset tersebut adalah pelanggar.
   Pertimbangkan untuk EXCLUDE ruleset ini dari eksperimen utama.

d) Jika SEMUA test cepat → ini adalah kontaminasi sistem saat eksperimen variance.
   Outlier dapat dieksklusi dengan justifikasi sistem.

Cleanup:
    rm -rf {WORK_DIR}
""")

# Cleanup repo
print(f"[Cleanup] Menghapus {REPO_PATH}...")
shutil.rmtree(REPO_PATH, ignore_errors=True)
print("Selesai.")