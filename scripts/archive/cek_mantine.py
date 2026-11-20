import os
import subprocess
from pathlib import Path
import shutil

REPO_URL = 'https://github.com/mantinedev/next-pages-template.git'
TARGET_COMMIT = 'aa8264c'
WORK_DIR = Path('mantine_temp_repo')

print("1. Cloning repository Mantinedev...")
# Hapus folder jika sudah ada sebelumnya
if WORK_DIR.exists():
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    
subprocess.run(['git', 'clone', '--quiet', REPO_URL, str(WORK_DIR)], check=True)

print(f"2. Checkout ke commit anomali ({TARGET_COMMIT})...")
# Dapatkan full hash
result = subprocess.run(['git', 'log', '--all', '--format=%H', '--abbrev-commit'], 
                        cwd=WORK_DIR, capture_output=True, text=True)
full_hash = next((line for line in result.stdout.split('\n') if line.startswith(TARGET_COMMIT)), None)

subprocess.run(['git', 'checkout', '-f', '--quiet', full_hash], cwd=WORK_DIR, check=True)

print("3. Menghitung dimensi file...")
total_size = 0
total_files = 0

for root, dirs, files in os.walk(WORK_DIR):
    # Abaikan folder .git agar murni menghitung source code
    if '.git' in dirs:
        dirs.remove('.git')
    for f in files:
        fp = os.path.join(root, f)
        if not os.path.islink(fp):
            total_size += os.path.getsize(fp)
            total_files += 1

size_mb = total_size / (1024 * 1024)

print("=========================================")
print(f"UKURAN REPO MANTINEDEV: {size_mb:.2f} MB")
print(f"TOTAL BERKAS          : {total_files} file")
print("=========================================")

# Cleanup
shutil.rmtree(WORK_DIR, ignore_errors=True)