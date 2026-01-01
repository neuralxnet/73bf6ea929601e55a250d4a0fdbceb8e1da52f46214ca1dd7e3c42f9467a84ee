# Cloud Storage Bucket Reconnaissance Implementation

## Overview
This implementation adds multi-cloud bucket enumeration capabilities to the repository, supporting Azure Blob Storage, Linode Object Storage, IBM Cloud Object Storage, and DigitalOcean Spaces.

## Implementation Details

### New Script: cloud_storage_recon_chunked.py
Located at: `.github/cloud_storage_recon_chunked.py`

#### Supported Cloud Providers
1. **Azure Blob Storage**
   - URL Format: `https://{bucket}.blob.core.windows.net`
   - Global service (no regional variations)
   - Checks for public bucket listing via `?comp=list` parameter

2. **Linode Object Storage**
   - URL Format: `https://{bucket}.{region}.linodeobjects.com`
   - Regions: us-east, us-central, us-west, us-southeast, ca-central, eu-west, eu-central, ap-south, ap-northeast, ap-southeast

3. **IBM Cloud Object Storage**
   - URL Format: `https://{bucket}.{region}.cloud-object-storage.appdomain.cloud`
   - Regions: us-south, us-east, us-west, eu-gb, eu-de, jp-tok, jp-osa, au-syd, ca-tor, br-sao

4. **DigitalOcean Spaces**
   - URL Format: `https://{bucket}.{region}.digitaloceanspaces.com`
   - Regions: nyc3, sfo2, sfo3, ams3, sgp1, fra1, tor1, blr1, syd1

### Key Features

#### Same Methodology as S3 Recon
- Chunked processing for memory efficiency
- State management for resumable scans
- Permutation engine with 4 levels (0-3)
- Domain-based tracking to avoid duplicate scans
- Concurrent scanning with configurable worker threads

#### Storage Mechanism
- Results stored in same `results/` directory
- State stored in same `state/` directory
- Separate state file: `cloud_storage_domain_state.json`
- Output files named: `{date}_{domain}_cloud_chunk_{id}.json`

#### Permutation System
Same intelligent permutation system as S3:
- Level 0: Base words only
- Level 1: Basic environment combinations
- Level 2: Enhanced with years, numbers, regions (default)
- Level 3: Comprehensive with prefixes, suffixes, combos

### New GitHub Actions Workflow: cloud-storage-recon.yml
Located at: `.github/workflows/cloud-storage-recon.yml`

#### Workflow Features
- Runs on schedule: Every hour at 30 minutes past (`:30`)
- Manual dispatch with customizable parameters
- Uses same base_wordlist.txt as S3 recon
- Commits results back to repository
- Conflict resolution for concurrent runs

#### Workflow Parameters
- `chunk_size`: Words per chunk (default: 1)
- `workers`: Concurrent workers (default: 30)
- `domains_per_hour`: Rate limiting (default: 1)
- `permutation_level`: 0-3 (default: 1)
- `providers`: Space-separated list (default: all)

### Usage Examples

#### Basic Usage
```bash
python3 .github/cloud_storage_recon_chunked.py base_wordlist.txt
```

#### Scan Specific Providers
```bash
python3 .github/cloud_storage_recon_chunked.py base_wordlist.txt --providers azure linode
```

#### Enhanced Permutations
```bash
python3 .github/cloud_storage_recon_chunked.py base_wordlist.txt --permutation-level 3
```

#### Rate Limited Scan
```bash
python3 .github/cloud_storage_recon_chunked.py base_wordlist.txt --domains-per-hour 5
```

### Output Format
JSON files with the following structure:
```json
{
  "chunk_id": 1,
  "domain": "example",
  "date": "2026-01-01",
  "timestamp": "2026-01-01T10:00:00",
  "providers": ["azure", "linode", "ibm", "digitalocean"],
  "results": {
    "public": [
      {
        "url": "https://example.blob.core.windows.net",
        "bucket": "example",
        "provider": "azure",
        "region": "global",
        "status": 200,
        "access": "public",
        "timestamp": "2026-01-01T10:00:00"
      }
    ],
    "private": []
  },
  "stats": {
    "total_checked": 100,
    "public_found": 1,
    "private_found": 0
  }
}
```

### Integration with Existing System
- Uses same `base_wordlist.txt` file
- Uses same `list.txt` environment file
- Uses same `results/` directory
- Uses same `state/` directory
- Same conflict resolution strategy
- Same retry logic for Git operations

### Differences from S3 Recon
1. Separate state file to track cloud storage progress independently
2. Multiple provider support in single run
3. Different URL formats per provider
4. Regional variations per provider (except Azure)
5. Output files include `_cloud_` identifier

### Testing
Script has been tested with:
- All cloud providers individually
- Multiple providers simultaneously
- All permutation levels (0-3)
- Different rate limiting configurations
- State persistence and resume functionality

### Performance Considerations
- Azure: 1 request per bucket (global service)
- Linode: 10 requests per bucket (10 regions)
- IBM: 10 requests per bucket (10 regions)
- DigitalOcean: 9 requests per bucket (9 regions)

Total: Up to 30 requests per bucket when scanning all providers

With permutation level 2 and 1 domain:
- ~19,000 bucket name variations
- ~570,000 total requests (all providers)
- Estimated time: 15-30 minutes at 30 workers

### Security
- No credentials required (public bucket enumeration only)
- Read-only operations
- No data exfiltration
- Respects rate limiting
- Handles timeouts gracefully

### Maintenance
To add new regions or providers:
1. Add region list constant (e.g., `NEW_PROVIDER_REGIONS`)
2. Add check method (e.g., `check_new_provider_bucket()`)
3. Update `scan_bucket()` method to handle new provider
4. Update `run_chunk()` to generate combinations
5. Update workflow documentation

### Continuous Research Mode
Like S3 recon, the script supports continuous research:
1. Scans all domains at configured permutation level
2. When complete, automatically increases permutation level
3. Re-scans all domains with enhanced patterns
4. Continues until level 3 is reached
5. No manual intervention required
