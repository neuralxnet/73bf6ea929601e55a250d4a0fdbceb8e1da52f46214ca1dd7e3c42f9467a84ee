#!/usr/bin/env python3

import sys
import json
import argparse
import requests
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import threading
import os
from datetime import datetime
import hashlib
import gzip
import struct
from urllib3.exceptions import LocationParseError

AZURE_REGIONS = [
    'eastus', 'eastus2', 'westus', 'westus2', 'centralus',
    'northcentralus', 'southcentralus', 'westcentralus',
    'canadacentral', 'canadaeast',
    'brazilsouth', 'brazilsoutheast',
    'northeurope', 'westeurope', 'uksouth', 'ukwest',
    'francecentral', 'francesouth', 'germanywestcentral',
    'norwayeast', 'norwaywest', 'switzerlandnorth', 'switzerlandwest',
    'swedencentral', 'polandcentral',
    'eastasia', 'southeastasia',
    'australiaeast', 'australiasoutheast', 'australiacentral',
    'japaneast', 'japanwest', 'koreacentral', 'koreasouth',
    'southindia', 'centralindia', 'westindia',
    'uaenorth', 'uaecentral',
    'southafricanorth', 'southafricawest'
]

LINODE_REGIONS = [
    'us-east', 'us-central', 'us-west', 'us-southeast',
    'ca-central',
    'eu-west', 'eu-central',
    'ap-south', 'ap-northeast', 'ap-southeast'
]

IBM_REGIONS = [
    'us-south', 'us-east', 'us-west',
    'eu-gb', 'eu-de',
    'jp-tok', 'jp-osa',
    'au-syd',
    'ca-tor',
    'br-sao'
]

DIGITALOCEAN_REGIONS = [
    'nyc3', 'sfo2', 'sfo3',
    'ams3',
    'sgp1',
    'fra1',
    'tor1',
    'blr1',
    'syd1'
]

SEPARATORS = ['', '-', '_', '.']

SEPARATORS_NO_DOT = ['', '-', '_']
SEPARATORS_DASH_ONLY = ['-', '']

DEFAULT_ENVIRONMENTS = [
    '', 'dev', 'prod', 'test', 'staging', 'stage', 'qa', 'uat',
    'backup', 'backups', 'data', 'files', 'assets',
    'public', 'private', 'internal', 'external',
    'www', 'api', 'app', 'web', 'mobile', 'admin'
]

YEARS = ['2020', '2021', '2022', '2023', '2024', '2025']
SHORT_YEARS = ['20', '21', '22', '23', '24', '25']
NUMBERS = ['1', '2', '3', '01', '02', '03', 'v1', 'v2', 'v3']
REGIONS_SHORT = ['us', 'eu', 'asia', 'ap', 'ca', 'uk', 'au', 'br', 'de', 'fr', 'jp']
COMMON_SUFFIXES = ['bucket', 'storage', 'store', 'media', 'content', 'static', 'assets', 'archive']
COMMON_PREFIXES = ['my', 'company', 'project', 'app', 'service', 'cloud']

class CloudStorageReconChunked:
    def __init__(self, wordlist, timeout=10, max_workers=30, public_only=False, 
                 env_file=None, verbose=False, chunk_size=50, state_dir='state', 
                 output_dir='results', resume=True, domains_per_hour=None, max_state_size_mb=28,
                 permutation_level=2, providers=None):
        self.wordlist = wordlist
        self.timeout = timeout
        self.max_workers = max_workers
        self.public_only = public_only
        self.env_file = env_file
        self.verbose = verbose
        self.chunk_size = chunk_size
        self.state_dir = state_dir
        self.output_dir = output_dir
        self.resume = resume
        self.domains_per_hour = domains_per_hour
        self.max_state_size_mb = max_state_size_mb
        self.max_state_size_bytes = max_state_size_mb * 1024 * 1024
        self.permutation_level = permutation_level
        self.providers = providers or ['azure', 'linode', 'ibm', 'digitalocean']
        self.environments = self.load_environments()
        self.results = {'public': [], 'private': []}
        self.total_checked = 0
        self.lock = threading.Lock()
        self.scanned_buckets = set()
        
        os.makedirs(state_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)
    
    def load_environments(self):
        if self.env_file and os.path.exists(self.env_file):
            try:
                with open(self.env_file, 'r', encoding='utf-8', errors='ignore') as f:
                    envs = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                    print(f"[*] Loaded {len(envs)} environments from {self.env_file}")
                    return envs
            except Exception as e:
                print(f"[!] Error loading environment file: {e}")
                print(f"[*] Using default environments")
                return DEFAULT_ENVIRONMENTS
        return DEFAULT_ENVIRONMENTS
        
    def load_wordlist(self, filepath):
        words = []
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith('#'):
                        words.append(word)
        except Exception as e:
            print(f"[!] Error loading wordlist: {e}")
            sys.exit(1)
        return words
    
    def generate_bucket_names(self, words):
        buckets = set()
        
        for word in words:
            word = word.lower().replace(' ', '-').replace('*', '').replace('.', '-')
            
            if not word:
                continue
            
            buckets.add(word)
            
            if self.permutation_level == 0:
                continue
            
            for env in self.environments:
                if env:
                    for sep in SEPARATORS:
                        buckets.add(f"{word}{sep}{env}")
                        buckets.add(f"{env}{sep}{word}")
            
            if self.permutation_level >= 2:
                for year in YEARS:
                    for sep in SEPARATORS:
                        buckets.add(f"{word}{sep}{year}")
                        buckets.add(f"{year}{sep}{word}")
                
                for year in SHORT_YEARS:
                    for sep in SEPARATORS_DASH_ONLY:
                        buckets.add(f"{word}{sep}{year}")
                        buckets.add(f"{year}{sep}{word}")
                
                for num in NUMBERS:
                    for sep in SEPARATORS:
                        buckets.add(f"{word}{sep}{num}")
                
                for region in REGIONS_SHORT:
                    for sep in SEPARATORS_NO_DOT:
                        buckets.add(f"{word}{sep}{region}")
                        buckets.add(f"{region}{sep}{word}")
            
            if self.permutation_level >= 3:
                for suffix in COMMON_SUFFIXES:
                    for sep in SEPARATORS_NO_DOT:
                        buckets.add(f"{word}{sep}{suffix}")
                
                for prefix in COMMON_PREFIXES:
                    for sep in SEPARATORS_NO_DOT:
                        buckets.add(f"{prefix}{sep}{word}")
                
                for env in ['dev', 'prod', 'test', 'staging']:
                    for year in ['2023', '2024', '2025']:
                        for sep in ['-', '_']:
                            buckets.add(f"{word}{sep}{env}{sep}{year}")
                            buckets.add(f"{word}{sep}{year}{sep}{env}")
                
                for env in ['dev', 'prod', 'staging', 'test']:
                    for region in ['us', 'eu', 'ap']:
                        for sep in ['-', '_']:
                            buckets.add(f"{word}{sep}{env}{sep}{region}")
                            buckets.add(f"{word}{sep}{region}{sep}{env}")
        
        return list(buckets)
    
    def get_bucket_hash(self, bucket_name, provider, region):
        return hashlib.md5(f"{bucket_name}:{provider}:{region}".encode()).hexdigest()
    
    def load_state(self, chunk_id):
        return set()
    
    def save_state(self, chunk_id, scanned_hashes):
        pass
    
    def load_domain_state(self):
        state_file = os.path.join(self.state_dir, "cloud_storage_domain_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    return set(state.get('scanned_domains', [])), state.get('last_scan_time', None)
            except:
                return set(), None
        return set(), None
    
    def save_domain_state(self, scanned_domains, last_scan_time=None):
        state_file = os.path.join(self.state_dir, "cloud_storage_domain_state.json")
        try:
            with open(state_file, 'w') as f:
                json.dump({
                    'scanned_domains': list(scanned_domains),
                    'last_scan_time': last_scan_time or datetime.now().isoformat(),
                    'updated': datetime.now().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"[!] Error saving domain state: {e}")
    
    def get_domain_hash(self, domain):
        return hashlib.md5(domain.encode()).hexdigest()
    
    def check_azure_blob(self, bucket_name, region):
        urls = [
            f"https://{bucket_name}.blob.core.windows.net",
            f"https://{bucket_name}.blob.core.windows.net/?comp=list"
        ]
        
        for url in urls:
            if self.verbose:
                print(f"[~] Checking Azure: {url}")
            
            try:
                response = requests.head(url, timeout=self.timeout, allow_redirects=True)
                
                if self.verbose:
                    print(f"[>] Response: {url} -> Status: {response.status_code}")
                
                if response.status_code in [200, 301, 302, 307, 409]:
                    access_type = self.determine_access_azure(url)
                    return {
                        'url': url,
                        'bucket': bucket_name,
                        'provider': 'azure',
                        'region': region,
                        'status': response.status_code,
                        'access': access_type,
                        'timestamp': datetime.now().isoformat()
                    }
                    
            except requests.exceptions.Timeout:
                if self.verbose:
                    print(f"[!] Timeout: {url}")
                continue
            except LocationParseError as e:
                if self.verbose:
                    print(f"[!] LocationParseError: {url} -> {e}")
                continue
            except requests.exceptions.RequestException as e:
                if self.verbose:
                    print(f"[!] Error: {url} -> {type(e).__name__}")
                continue
        
        return None
    
    def determine_access_azure(self, url):
        try:
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                if '<?xml' in response.text or 'EnumerationResults' in response.text:
                    return 'public'
                return 'accessible'
            elif response.status_code == 403:
                return 'private'
            elif response.status_code == 409:
                return 'exists'
            elif response.status_code in [301, 302, 307]:
                return 'exists'
            else:
                return 'unknown'
                
        except LocationParseError:
            return 'unknown'
        except requests.exceptions.RequestException:
            return 'private'
    
    def check_linode_bucket(self, bucket_name, region):
        url = f"https://{bucket_name}.{region}.linodeobjects.com"
        
        if self.verbose:
            print(f"[~] Checking Linode: {url}")
        
        try:
            response = requests.head(url, timeout=self.timeout, allow_redirects=True)
            
            if self.verbose:
                print(f"[>] Response: {url} -> Status: {response.status_code}")
            
            if response.status_code in [200, 301, 302, 307]:
                access_type = self.determine_access_generic(url)
                return {
                    'url': url,
                    'bucket': bucket_name,
                    'provider': 'linode',
                    'region': region,
                    'status': response.status_code,
                    'access': access_type,
                    'timestamp': datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            if self.verbose:
                print(f"[!] Timeout: {url}")
        except LocationParseError as e:
            if self.verbose:
                print(f"[!] LocationParseError: {url} -> {e}")
        except requests.exceptions.RequestException as e:
            if self.verbose:
                print(f"[!] Error: {url} -> {type(e).__name__}")
        
        return None
    
    def check_ibm_bucket(self, bucket_name, region):
        url = f"https://{bucket_name}.{region}.cloud-object-storage.appdomain.cloud"
        
        if self.verbose:
            print(f"[~] Checking IBM: {url}")
        
        try:
            response = requests.head(url, timeout=self.timeout, allow_redirects=True)
            
            if self.verbose:
                print(f"[>] Response: {url} -> Status: {response.status_code}")
            
            if response.status_code in [200, 301, 302, 307]:
                access_type = self.determine_access_generic(url)
                return {
                    'url': url,
                    'bucket': bucket_name,
                    'provider': 'ibm',
                    'region': region,
                    'status': response.status_code,
                    'access': access_type,
                    'timestamp': datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            if self.verbose:
                print(f"[!] Timeout: {url}")
        except LocationParseError as e:
            if self.verbose:
                print(f"[!] LocationParseError: {url} -> {e}")
        except requests.exceptions.RequestException as e:
            if self.verbose:
                print(f"[!] Error: {url} -> {type(e).__name__}")
        
        return None
    
    def check_digitalocean_space(self, bucket_name, region):
        url = f"https://{bucket_name}.{region}.digitaloceanspaces.com"
        
        if self.verbose:
            print(f"[~] Checking DigitalOcean: {url}")
        
        try:
            response = requests.head(url, timeout=self.timeout, allow_redirects=True)
            
            if self.verbose:
                print(f"[>] Response: {url} -> Status: {response.status_code}")
            
            if response.status_code in [200, 301, 302, 307]:
                access_type = self.determine_access_generic(url)
                return {
                    'url': url,
                    'bucket': bucket_name,
                    'provider': 'digitalocean',
                    'region': region,
                    'status': response.status_code,
                    'access': access_type,
                    'timestamp': datetime.now().isoformat()
                }
                
        except requests.exceptions.Timeout:
            if self.verbose:
                print(f"[!] Timeout: {url}")
        except LocationParseError as e:
            if self.verbose:
                print(f"[!] LocationParseError: {url} -> {e}")
        except requests.exceptions.RequestException as e:
            if self.verbose:
                print(f"[!] Error: {url} -> {type(e).__name__}")
        
        return None
    
    def determine_access_generic(self, url):
        try:
            response = requests.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                if '<?xml' in response.text or 'ListBucketResult' in response.text:
                    return 'public'
                return 'accessible'
            elif response.status_code == 403:
                return 'private'
            elif response.status_code in [301, 302, 307]:
                return 'exists'
            else:
                return 'unknown'
                
        except LocationParseError:
            return 'unknown'
        except requests.exceptions.RequestException:
            return 'private'
    
    def scan_bucket(self, bucket_name, provider, region, scanned_hashes):
        bucket_hash = self.get_bucket_hash(bucket_name, provider, region)
        
        if bucket_hash in scanned_hashes:
            if self.verbose:
                print(f"[*] Skipping already scanned: {bucket_name} on {provider} in {region}")
            return None
        
        with self.lock:
            self.total_checked += 1
            checked = self.total_checked
        
        if self.verbose:
            print(f"[*] [{checked}] Scanning: {bucket_name} on {provider} in {region}")
        
        result = None
        
        if provider == 'azure':
            result = self.check_azure_blob(bucket_name, region)
        elif provider == 'linode':
            result = self.check_linode_bucket(bucket_name, region)
        elif provider == 'ibm':
            result = self.check_ibm_bucket(bucket_name, region)
        elif provider == 'digitalocean':
            result = self.check_digitalocean_space(bucket_name, region)
        
        with self.lock:
            scanned_hashes.add(bucket_hash)
        
        if result:
            access = result['access']
            url = result['url']
            provider_name = result['provider'].upper()
            
            if access in ['public', 'accessible']:
                print(f"[+] PUBLIC  {url} | Bucket: {bucket_name} | Provider: {provider_name} | Region: {region}")
                with self.lock:
                    self.results['public'].append(result)
                return result
            elif not self.public_only:
                print(f"[-] PRIVATE {url} | Bucket: {bucket_name} | Provider: {provider_name} | Region: {region}")
                with self.lock:
                    self.results['private'].append(result)
                return result
        else:
            if self.verbose:
                print(f"[x] [{checked}] Not found: {bucket_name} on {provider} in {region}")
        
        return None
    
    def save_chunk_results(self, chunk_id, domain):
        date_str = datetime.now().strftime('%Y-%m-%d')
        domain_clean = domain.replace('/', '_').replace(':', '_')
        
        output_file = os.path.join(self.output_dir, f"{date_str}_{domain_clean}_cloud_chunk_{chunk_id}.json")
        
        try:
            with open(output_file, 'w') as f:
                json.dump({
                    'chunk_id': chunk_id,
                    'domain': domain,
                    'date': date_str,
                    'timestamp': datetime.now().isoformat(),
                    'providers': self.providers,
                    'results': self.results,
                    'stats': {
                        'total_checked': self.total_checked,
                        'public_found': len(self.results['public']),
                        'private_found': len(self.results['private'])
                    }
                }, f, indent=2)
            print(f"[*] Results saved to {output_file}")
        except Exception as e:
            print(f"[!] Error saving results: {e}")
    
    def run_chunk(self, bucket_names, chunk_id, domain):
        print(f"\n{'='*60}")
        print(f"[*] Processing Chunk {chunk_id}")
        print(f"[*] Domain: {domain}")
        print(f"[*] Bucket names in chunk: {len(bucket_names)}")
        print(f"[*] Providers: {', '.join([p.upper() for p in self.providers])}")
        
        scanned_hashes = set()
        
        combinations = []
        for bucket in bucket_names:
            for provider in self.providers:
                if provider == 'azure':
                    combinations.append((bucket, provider, 'global'))
                elif provider == 'linode':
                    for region in LINODE_REGIONS:
                        combinations.append((bucket, provider, region))
                elif provider == 'ibm':
                    for region in IBM_REGIONS:
                        combinations.append((bucket, provider, region))
                elif provider == 'digitalocean':
                    for region in DIGITALOCEAN_REGIONS:
                        combinations.append((bucket, provider, region))
        
        print(f"[*] Total combinations to check: {len(combinations)}")
        print(f"[*] Using {self.max_workers} concurrent workers")
        print(f"[*] Timeout per request: {self.timeout} seconds")
        print(f"[*] Starting chunk scan...\n")
        
        start_time = time.time()
        found_count = 0
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.scan_bucket, bucket, provider, region, scanned_hashes): (bucket, provider, region)
                for bucket, provider, region in combinations
            }
            
            completed = 0
            total = len(futures)
            
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                if result:
                    found_count += 1
                
                if not self.verbose and completed % 50 == 0:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(f"[*] Progress: {completed}/{total} ({(completed/total*100):.1f}%) | Rate: {rate:.1f} req/s | Found: {found_count}")
        
        elapsed_time = time.time() - start_time
        
        print(f"\n{'='*60}")
        print(f"[*] Chunk {chunk_id} completed in {elapsed_time:.2f} seconds")
        print(f"[*] Total requests made: {self.total_checked}")
        print(f"[*] Average rate: {self.total_checked/elapsed_time:.1f} requests/second")
        print(f"[*] Found {len(self.results['public'])} public buckets")
        print(f"[*] Found {len(self.results['private'])} private buckets")
        print(f"{'='*60}")
        
        self.save_chunk_results(chunk_id, domain)
        
        return self.results
    
    def run(self):
        all_words = []
        for wordlist_file in self.wordlist:
            print(f"[*] Loading wordlist: {wordlist_file}")
            words = self.load_wordlist(wordlist_file)
            all_words.extend(words)
        
        print(f"[*] Loaded {len(all_words)} words from {len(self.wordlist)} wordlist(s)")
        print(f"[*] Permutation level: {self.permutation_level}")
        print(f"[*] Cloud providers: {', '.join([p.upper() for p in self.providers])}")
        
        scanned_domains, last_scan_time = self.load_domain_state()
        print(f"[*] Previously scanned domains: {len(scanned_domains)}")
        if last_scan_time:
            print(f"[*] Last scan time: {last_scan_time}")
        
        remaining_domains = [word for word in all_words if self.get_domain_hash(word) not in scanned_domains]
        print(f"[*] Remaining domains to scan: {len(remaining_domains)}")
        
        if not remaining_domains:
            print("[*] All base domains have been scanned.")
            
            if self.permutation_level < 3:
                print(f"[*] Starting additional permutation round with level {self.permutation_level + 1}")
                original_level = self.permutation_level
                self.permutation_level += 1
                
                state_file = os.path.join(self.state_dir, "cloud_storage_domain_state.json")
                if os.path.exists(state_file):
                    try:
                        with open(state_file, 'r') as f:
                            state = json.load(f)
                            state['permutation_level_completed'] = original_level
                            state['additional_rounds'] = state.get('additional_rounds', 0) + 1
                        with open(state_file, 'w') as f:
                            json.dump(state, f, indent=2)
                    except:
                        pass
                
                remaining_domains = all_words
                print(f"[*] Re-scanning {len(remaining_domains)} domains with enhanced permutations")
            else:
                print("[*] All permutation levels have been exhausted. No more work to do.")
                return
        
        if self.domains_per_hour:
            domains_to_process = remaining_domains[:self.domains_per_hour]
            print(f"[*] Processing {len(domains_to_process)} domains (limited to {self.domains_per_hour} per hour)")
        else:
            domains_to_process = remaining_domains
            print(f"[*] Processing all {len(domains_to_process)} remaining domains")
        
        chunks = [domains_to_process[i:i + self.chunk_size] for i in range(0, len(domains_to_process), self.chunk_size)]
        print(f"[*] Split into {len(chunks)} chunks of up to {self.chunk_size} words each")
        
        scan_start_time = datetime.now()
        domains_scanned_this_run = []
        
        for idx, chunk in enumerate(chunks):
            print(f"\n[*] Starting chunk {idx + 1}/{len(chunks)}")
            
            domain = chunk[0] if chunk else "unknown"
            
            bucket_names = self.generate_bucket_names(chunk)
            print(f"[*] Generated {len(bucket_names)} bucket name variations")
            
            self.results = {'public': [], 'private': []}
            self.total_checked = 0
            
            self.run_chunk(bucket_names, idx + 1, domain)
            
            for word in chunk:
                domain_hash = self.get_domain_hash(word)
                scanned_domains.add(domain_hash)
                domains_scanned_this_run.append(word)
            
            self.save_domain_state(scanned_domains, scan_start_time.isoformat())
            
            time.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"[*] Scan session completed!")
        print(f"[*] Domains scanned in this run: {len(domains_scanned_this_run)}")
        print(f"[*] Total domains scanned so far: {len(scanned_domains)}")
        print(f"[*] Remaining domains: {len(all_words) - len(scanned_domains)}")
        print(f"[*] Permutation level used: {self.permutation_level}")
        print(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser(description='Cloud Storage Bucket Mass Reconnaissance Tool - Chunked Version')
    parser.add_argument('wordlist', nargs='+', help='Wordlist file(s) to use')
    parser.add_argument('-p', '--public', action='store_true', help='Only show public buckets')
    parser.add_argument('-t', '--timeout', type=int, default=8, help='Request timeout (default: 8)')
    parser.add_argument('-w', '--workers', type=int, default=30, help='Concurrent workers (default: 30)')
    parser.add_argument('-e', '--env-file', help='Environment/keywords file (default: list.txt)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose mode - show all attempts')
    parser.add_argument('-c', '--chunk-size', type=int, default=1, help='Words per chunk (default: 1 for focused scanning)')
    parser.add_argument('--state-dir', default='state', help='State directory (default: state)')
    parser.add_argument('--output-dir', default='results', help='Output directory (default: results)')
    parser.add_argument('--no-resume', action='store_true', help='Disable resume from previous state')
    parser.add_argument('--domains-per-hour', type=int, default=1, help='Number of domains to scan per hour (default: 1 for targeted scanning)')
    parser.add_argument('--max-state-size', type=int, default=28, help='Maximum state file size in MB before rotation (default: 28)')
    parser.add_argument('--permutation-level', type=int, default=2, choices=[0, 1, 2, 3],
                        help='Permutation level: 0=base only, 1=basic envs, 2=+years/numbers/regions (default), 3=+prefixes/suffixes/combos')
    parser.add_argument('--providers', nargs='+', default=['azure', 'linode', 'ibm', 'digitalocean'],
                        choices=['azure', 'linode', 'ibm', 'digitalocean'],
                        help='Cloud providers to scan (default: all)')
    
    args = parser.parse_args()
    
    env_file = args.env_file if args.env_file else 'list.txt'
    
    print("""
╔═══════════════════════════════════════════════════╗
║   Cloud Storage Mass Recon Scanner - Chunked     ║
║   Azure | Linode | IBM | DigitalOcean            ║
║   Memory-Safe Chunked Processing                 ║
║   Enhanced Permutation Engine                    ║
╚═══════════════════════════════════════════════════╝
    """)
    
    recon = CloudStorageReconChunked(
        wordlist=args.wordlist,
        timeout=args.timeout,
        max_workers=args.workers,
        public_only=args.public,
        env_file=env_file,
        verbose=args.verbose,
        chunk_size=args.chunk_size,
        state_dir=args.state_dir,
        output_dir=args.output_dir,
        resume=not args.no_resume,
        domains_per_hour=args.domains_per_hour,
        max_state_size_mb=args.max_state_size,
        permutation_level=args.permutation_level,
        providers=args.providers
    )
    
    recon.run()

if __name__ == '__main__':
    main()
