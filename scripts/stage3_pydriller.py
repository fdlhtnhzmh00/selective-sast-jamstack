import os
import re
import hashlib
import pandas as pd
from pathlib import Path
from tqdm import tqdm
from pydriller import Repository

INPUT_FILE = Path("data/interim/02_selected_repositories.parquet")
OUTPUT_DIR = Path("data/interim/commits")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Regex untuk eksklusi (Hard Rule metodologi)
LOCKFILES_REGEX = re.compile(r'(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|Gemfile\.lock|go\.sum)')
GENERATED_REGEX = re.compile(r'(^|/)(dist|build|vendor|out|\.next)/|\.min\.(js|css)$')

def hash_string(text):
    """Menyamarkan data personal author (etika penelitian)."""
    if not text:
        return None
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def is_bot(author_name, author_email):
    """Deteksi bot sederhana untuk filtering."""
    name = str(author_name).lower()
    email = str(author_email).lower()
    return '[bot]' in name or 'bot@' in email or 'dependabot' in name or 'renovate' in name or 'snyk' in name

def is_revert(msg):
    """Deteksi commit revert via Regex."""
    return bool(re.match(r'^revert\b', str(msg).lower().strip()))

def mine_repository(repo_path, repo_name):
    commits_data = []
    
    try:
        # Traverse dari HEAD secara linier
        for commit in Repository(str(repo_path), only_no_merge=False).traverse_commits():
            author_hashed = hash_string(commit.author.email)
            domain = commit.author.email.split('@')[-1] if '@' in commit.author.email else None
            bot_flag = is_bot(commit.author.name, commit.author.email)
            revert_flag = is_revert(commit.msg)
            
            parent_hashes = ",".join(commit.parents)
            
            for mod in commit.modified_files:
                file_path = mod.new_path or mod.old_path
                
                # Hard Rule: Abaikan lockfiles, generated assets, dan vendor
                if not file_path or LOCKFILES_REGEX.search(file_path) or GENERATED_REGEX.search(file_path):
                    continue
                
                commits_data.append({
                    'repo_name': repo_name,
                    'commit_hash': commit.hash,
                    'parent_hashes': parent_hashes,
                    'commit_timestamp_utc': commit.committer_date.astimezone(pd.Timestamp.utcnow().tz).isoformat(),
                    'author_id_hashed': author_hashed,
                    'author_email_domain': domain,
                    'is_bot_author': bot_flag,
                    'is_revert': revert_flag,
                    'is_merge_commit': commit.merge,
                    'file_path_at_commit': file_path,
                    'change_type': mod.change_type.name,
                    'lines_added': mod.added_lines,
                    'lines_deleted': mod.deleted_lines,
                    'nloc_before': mod.nloc if mod.change_type.name != 'ADD' else 0, # Approximation
                    'complexity_after': mod.complexity,
                    # Modification-pattern flags
                    'touches_config': bool(re.search(r'(\.config\.(js|ts|mjs)|gatsby-.*?\.js)$', file_path)),
                    'touches_ci': bool(re.search(r'(\.github/|\.gitlab-ci|netlify\.toml|\.circleci/)', file_path)),
                    'touches_auth': bool(re.search(r'(auth|session|token|jwt|oauth|login)', file_path.lower())),
                    'touches_api': bool(re.search(r'(pages/api/|app/api/|netlify/functions/|functions/)', file_path.lower()))
                })
    except Exception as e:
        print(f"\n[Warning] Traversing gagal pada {repo_name} (mungkin force-push history). Error: {str(e)}")
        return None
        
    return pd.DataFrame(commits_data)

def main():
    df_repos = pd.read_parquet(INPUT_FILE)
    
    print("Memulai Tahap 3: Commit-Level Mining dengan PyDriller...")
    
    # Progress bar berbasis repositori
    pbar = tqdm(total=len(df_repos), desc="Mining Repositori")
    
    for _, row in df_repos.iterrows():
        repo_name = row['full_name']
        safe_name = repo_name.replace("/", "_")
        repo_path = Path("repos") / safe_name
        output_path = OUTPUT_DIR / f"{safe_name}.parquet"
        
        if output_path.exists():
            pbar.update(1)
            continue # Melewati repositori yang sudah berhasil diproses (Idempotensi)
            
        if not repo_path.exists():
            print(f"\n[Skip] Direktori {repo_path} tidak ditemukan.")
            pbar.update(1)
            continue
            
        df_commits = mine_repository(repo_path, repo_name)
        
        if df_commits is not None and not df_commits.empty:
            df_commits.to_parquet(output_path, index=False)
            
        pbar.update(1)
        
    pbar.close()
    print("\nTahap 3 Selesai! Semua data modifikasi level-file telah diekstrak.")

if __name__ == "__main__":
    main()