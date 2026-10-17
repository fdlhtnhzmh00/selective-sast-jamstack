import os
import time
import requests
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# Configuration based on methodology [cite: 13, 23]
SSGS = ['next.js', 'gatsby', 'hugo', 'eleventy', 'astro', 'nuxt', 'svelte', 'jekyll']
MIN_STARS = 100
MIN_COMMITS = 200
OUTPUT_DIR = Path("data/interim")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def handle_rate_limit(response):
    """Menangani limitasi API GitHub dengan delay jika perlu."""
    if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers:
        if int(response.headers['X-RateLimit-Remaining']) == 0:
            reset_time = int(response.headers['X-RateLimit-Reset'])
            sleep_time = max(reset_time - int(time.time()), 0) + 5
            print(f"Rate limit tercapai. Menunggu {sleep_time} detik...")
            time.sleep(sleep_time)
            return True
    return False

def search_repositories(ssg, min_stars):
    """Mencari repositori berdasarkan SSG dan batasan minimum stars (IC1, IC9)."""
    # IC9: fork:false 
    query = f"{ssg} in:readme stars:>={min_stars} fork:false"
    url = f"https://api.github.com/search/repositories?q={query}&per_page=100"
    
    repos = []
    while url:
        response = requests.get(url, headers=HEADERS)
        if handle_rate_limit(response):
            continue
            
        if response.status_code != 200:
            print(f"Error fetching data: {response.status_code} - {response.text}")
            break
            
        data = response.json()
        repos.extend(data.get('items', []))
        
        # Pagination handling
        if 'next' in response.links:
            url = response.links['next']['url']
            time.sleep(1) # Delay agresif untuk stabilitas
        else:
            url = None
            
    return repos

def validate_repo(repo_data):
    """Memvalidasi IC2, IC6, IC7, IC8 melalui metadata."""
    repo_name = repo_data['full_name']
    
    # IC7: License presence 
    if not repo_data.get('license') or not repo_data['license'].get('spdx_id'):
        return None
        
    # IC8: Primary Language 
    valid_langs = ['JavaScript', 'TypeScript', 'Go', 'Ruby']
    if repo_data.get('language') not in valid_langs:
        return None
        
    # IC2: Repository Age >= 12 months 
    created_at = pd.to_datetime(repo_data['created_at']).tz_convert(None)
    age_months = (pd.Timestamp.utcnow().tz_localize(None) - created_at).days / 30
    if age_months < 12:
        return None
        
    return {
        'full_name': repo_name,
        'clone_url': repo_data['clone_url'],
        'default_branch': repo_data['default_branch'],
        'stars': repo_data['stargazers_count'],
        'language': repo_data['language'],
        'license': repo_data['license']['spdx_id'],
        'created_at': repo_data['created_at'],
        'updated_at': repo_data['updated_at']
    }

def main():
    all_valid_repos = []
    
    print("Memulai Tahap 1: Discovery & Filtering...")
    for ssg in SSGS:
        print(f"Mencari repositori untuk ekosistem: {ssg.upper()}...")
        raw_repos = search_repositories(ssg, MIN_STARS)
        
        for repo in raw_repos:
            validated = validate_repo(repo)
            if validated:
                validated['ssg_detected'] = ssg
                all_valid_repos.append(validated)
                
    # Deduplikasi dan persistensi
    df = pd.DataFrame(all_valid_repos).drop_duplicates(subset=['full_name'])
    
    output_path = OUTPUT_DIR / "01_repositories_metadata.parquet"
    df.to_parquet(output_path, index=False)
    
    print(f"Selesai. Ditemukan {len(df)} kandidat repositori. Data disimpan ke {output_path}")
    print("Kolom yang tersedia:", df.columns.tolist())

if __name__ == "__main__":
    main()