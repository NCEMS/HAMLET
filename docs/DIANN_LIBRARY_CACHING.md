# DIA-NN Spectral Library Caching

## Overview

To speed up DIA-NN quantification, spectral libraries are pre-built once per organism and cached in `assets/diann_libraries/`. The pipeline automatically uses cached libraries when available, or builds them fresh on first use.

## Building Library Cache

### Step 1: Activate Search Environment

```bash
export SEARCH_ENV_PATH=/home/ians/miniconda3/envs/search_env
```

### Step 2: Run Library Builder for Top 20 Organisms

```bash
cd /mnt/storage_2/ProdPool6
python src/python/build_diann_libraries.py --threads 16
```

**Options:**
- `--cache-dir <path>` - Cache directory (default: `workspace/assets/diann_libraries`)
- `--threads <N>` - Threads per library build (default: 8)
- `--organisms <taxid1,taxid2,...>` - Build specific organisms (default: top 20)
- `--skip-download` - Skip FASTA download, use cached files only

### Step 3: Add New Organisms as Needed

```bash
# Build for a specific organism
python src/python/build_diann_libraries.py --organisms 562  # E. coli

# Build for multiple organisms
python src/python/build_diann_libraries.py --organisms 9606,10090,10116  # Human, Mouse, Rat
```

## How It Works in Pipeline

### First Run (No Cache)

When processing a new organism:
1. Pipeline calls DIA-NN with `--fasta-search --gen-spec-lib`
2. DIA-NN generates spectral library from FASTA
3. Library is automatically cached to `assets/diann_libraries/{taxid}.tsv`
4. Search results returned

### Subsequent Runs (Cache Hit)

When processing the same organism again:
1. Pipeline detects cached library at `assets/diann_libraries/{taxid}.tsv`
2. Calls DIA-NN with `--lib <cached_library>` (much faster)
3. Skips library generation step entirely

## Cache Structure

```
workspace/
├── assets/
│   ├── diann_libraries/
│   │   ├── 9606.tsv              # Human
│   │   ├── 10090.tsv             # Mouse
│   │   ├── 10116.tsv             # Rat
│   │   ├── fasta_9606.fasta      # FASTA source (optional)
│   │   └── ...
```

## Library Size Expectations

| Organism | Proteins | Library Size | Build Time |
|----------|----------|--------------|------------|
| Human (9606) | 20,000+ | 300-500 MB | 30-60 min |
| Mouse (10090) | 17,000+ | 250-400 MB | 20-40 min |
| Yeast (559292) | 6,000+ | 50-100 MB | 5-10 min |
| E. coli (562) | 4,300+ | 30-50 MB | 2-5 min |

## Troubleshooting

### Library Build Fails

```bash
# Re-run with verbose output
python src/python/build_diann_libraries.py --organisms 9606 --threads 4

# Check if DIA-NN is accessible
echo $SEARCH_ENV_PATH
ls $SEARCH_ENV_PATH/opt/search_tools/diann/
```

### Pipeline Can't Find Cache

Verify cache exists:
```bash
ls -lah assets/diann_libraries/
```

If cache is empty, rebuild it:
```bash
python src/python/build_diann_libraries.py --organisms <your_taxid>
```

## Top 20 Organisms in Cache

By default, the builder pre-caches these organisms:

1. **9606** - Homo sapiens (Human)
2. **10090** - Mus musculus (Mouse)
3. **10116** - Rattus norvegicus (Rat)
4. **6239** - Caenorhabditis elegans
5. **7227** - Drosophila melanogaster (Fruit fly)
6. **559292** - Saccharomyces cerevisiae (Baker's yeast)
7. **284812** - Schizosaccharomyces pombe
8. **3702** - Arabidopsis thaliana
9. **7955** - Danio rerio (Zebrafish)
10. **8355** - Xenopus laevis (African clawed frog)
11. **9913** - Bos taurus (Cattle)
12. **9615** - Canis lupus familiaris (Dog)
13. **9826** - Sus scrofa (Pig)
14. **6945** - Gallus gallus (Chicken)
15. **511145** - Escherichia coli
16. **562** - Escherichia coli (generic)
17. **694009** - Bacillus subtilis
18. **1280** - Staphylococcus aureus
19. **2157** - Archaea (domain)
20. **2759** - Eukaryota (domain)

## Performance Impact

**Without caching (fresh library every run):**
- First run: 30-45 min (library build + quantify)
- Second run: 30-45 min (rebuilds library again)

**With caching (pre-built libraries):**
- First run (no cache): 30-45 min (builds once)
- Subsequent runs: 5-10 min (uses cache)

**Speedup: 3-9x faster on cache reuse** 🚀

## Adding Custom Organisms

Edit the `TOP_ORGANISMS` list in `build_diann_libraries.py`:

```python
TOP_ORGANISMS = [
    ("9606", "Homo sapiens (Human)"),
    ("10090", "Mus musculus (Mouse)"),
    # ... add your organism below
    ("12345", "Your custom organism"),
]
```

Then rebuild:
```bash
python src/python/build_diann_libraries.py
```
