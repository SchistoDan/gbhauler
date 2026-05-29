# gbhauler :truck:

**Bulk GenBank record retrieval via NCBI Entrez**

gbhaul fetches GenBank records from NCBI using accession numbers, GI numbers, or a full Entrez search string. It writes one `.gb` file per record and a tab-separated summary of query IDs, accessions, and titles — with sensible defaults, flexible filename conventions, and robust retry/error handling throughout.

---

## Features

- Three combinable input modes: file, CLI list, or Entrez search string
- Flexible output filename conventions: by accession, GI number, or record title
- Automatic filename sanitisation and collision resolution
- WebEnv-based paging for large search result sets
- Confirmation gate for searches returning >1,000 records
- Retry logic with backoff for transient NCBI errors
- Optional NCBI API key support for higher throughput
- Skip-and-warn on missing records with non-zero exit for pipeline awareness
- Comment lines (`#`) supported in input files

---

## Installation

gbhaul requires Python 3.10+ and [Biopython](https://biopython.org/).

```bash
pip install biopython
```

Then clone or download `gbhaul.py` and run it directly — no further installation needed.

```bash
git clone https://github.com/your-org/gbhaul.git
cd gbhaul
python gbhaul.py --help
```

---

## Quick start

```bash
# Fetch records from an accession list file
python gbhaul.py --email you@example.com -i accessions.txt -o ./genbank_out

# Fetch a few IDs directly from the command line
python gbhaul.py --email you@example.com --ids "AY123456,NM_001234.1,229639" -o ./out

# Use an Entrez search string to find and fetch records automatically
python gbhaul.py --email you@example.com \
    --search "txid229639[Organism:exp] AND mitochondrion[filter]" \
    -o ./mito_records
```

---

## Input modes

All three modes can be combined in a single run. When more than one mode is used, IDs are merged and deduplicated in the order `--input` → `--ids` → `--search`.

### `--input FILE`

A plain-text file of accession numbers or GI numbers, one per line. Comma-separated values on a single line are also accepted. Lines beginning with `#` are ignored.

```
# COI sequences — Schistosoma japonicum
AY123456
NM_001234.1
229639, AY999999
```

### `--ids ID[,ID,...]`

A comma-delimited list of accession/GI numbers supplied directly on the command line. Mixed types are supported.

```bash
--ids "AY123456,NM_001234.1,229639"
```

### `--search "QUERY"`

Any valid [NCBI Entrez search string](https://www.ncbi.nlm.nih.gov/books/NBK3837/). gbhaul runs `esearch` with WebEnv history, pages through all matching UIDs in batches of 500, then fetches each record via `efetch` — no intermediate ID list required.

```bash
--search "txid229639[Organism:exp] AND (mitochondrion[filter] AND (\"500\"[SLEN]:\"500000\"[SLEN]))"
```

> **Large result sets:** if a search returns more than 1,000 records, gbhaul will print the hit count and prompt for confirmation before proceeding.

---

## Output

For each successfully retrieved record gbhaul writes a GenBank flat-file:

```
<outdir>/
├── AY123456.1.gb
├── AY654321.1.gb
├── ...
└── gbhaul_summary.tsv
```

The summary TSV has three columns:

| `query_id` | `accession` | `title` |
|---|---|---|
| AY123456 | AY123456.1 | Schistosoma japonicum isolate ... |

### Filename conventions (`--name-by`)

| Mode | Filename | Fallback |
|---|---|---|
| `accession` *(default)* | `<accession.version>.gb` | — |
| `gi` | `<GI_number>.gb` | accession if GI absent |
| `title` | `<sanitised_record_title>.gb` | accession if title absent |

Title-based filenames have whitespace and filesystem-unsafe characters (`/ \ : * ? " < > |`) replaced with underscores and are truncated to 80 characters. Filename collisions across any mode are resolved automatically by appending `_1`, `_2`, and so on.

---

## Full argument reference

```
usage: gbhaul [-h] [-i FILE] [--ids ID[,ID,…]] [--search QUERY]
              [-o DIR] [--name-by MODE] [--summary FILE]
              --email EMAIL [--api-key KEY] [--db DATABASE] [-v]
```

### Input

| Argument | Description |
|---|---|
| `-i`, `--input FILE` | Path to a file of accession/GI numbers. One per line; comma-separated values accepted. Lines starting with `#` ignored. |
| `--ids ID[,ID,…]` | Comma-delimited accession/GI numbers supplied directly. Mixed types supported. |
| `--search QUERY` | NCBI Entrez search string. Fetched in addition to any `--input`/`--ids` records. |

### Output

| Argument | Default | Description |
|---|---|---|
| `-o`, `--outdir DIR` | `.` | Output directory. Created if it does not exist. |
| `--name-by MODE` | `accession` | Filename convention: `accession`, `gi`, or `title`. |
| `--summary FILE` | `gbhaul_summary.tsv` | Name of the summary TSV, written inside `--outdir`. |

### NCBI Entrez

| Argument | Required | Description |
|---|---|---|
| `--email EMAIL` | Yes | Your email address, required by NCBI policy for all Entrez use. |
| `--api-key KEY` | No | NCBI API key. Raises rate limit from ~3 to ~10 req/s. Recommended for large batches. Get one free at [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/). |
| `--db DATABASE` | No | Entrez database to query (default: `nucleotide`). Other options: `protein`, `nuccore`, `gene`. |

### Miscellaneous

| Argument | Description |
|---|---|
| `-v`, `--verbose` | Enable debug-level logging (UID resolution, paging detail, retry attempts). |

---

## Examples

**Fetch from a file, accession-named outputs:**
```bash
python gbhaul.py \
    --email you@example.com \
    -i accessions.txt \
    -o ./genbank_out
```

**Fetch a handful of mixed IDs, title-named outputs:**
```bash
python gbhaul.py \
    --email you@example.com \
    --ids "AY123456,NM_001234.1,229639" \
    --name-by title \
    -o ./out
```

**Entrez search, with API key for speed:**
```bash
python gbhaul.py \
    --email you@example.com \
    --api-key YOUR_NCBI_KEY \
    --search "txid229639[Organism:exp] AND mitochondrion[filter]" \
    --name-by accession \
    -o ./mito_records
```

**Combine search results with extra accessions; query the protein database:**
```bash
python gbhaul.py \
    --email you@example.com \
    --api-key YOUR_NCBI_KEY \
    --db protein \
    --search "Schistosoma japonicum[Organism] AND complete[Title]" \
    --ids "AAB12345,CAA99999" \
    --name-by gi \
    --summary sj_proteins.tsv \
    -o ./out
```

**Run inside a pipeline — detect partial failures via exit code:**
```bash
python gbhaul.py --email you@example.com -i ids.txt -o ./out
if [ $? -ne 0 ]; then
    echo "WARNING: one or more records were skipped — check the log."
fi
```

---

## NCBI usage policy

NCBI requires that all Entrez API users identify themselves with a valid email address via `--email`. For bulk queries, obtaining a free [NCBI API key](https://www.ncbi.nlm.nih.gov/account/) is strongly recommended — it raises the allowed request rate from 3 to 10 per second and reduces the chance of temporary blocks during large runs. Please review [NCBI's usage guidelines](https://www.ncbi.nlm.nih.gov/home/about/policies/) before running large batch jobs.

---

## Error handling

| Situation | Behaviour |
|---|---|
| Record not found | Logged as a warning; record skipped |
| Transient network/server error | Retried up to 3 times with 5 s backoff |
| All retries exhausted | Logged as an error; record skipped |
| Any records skipped | Script exits with code `1` |
| Search >1,000 hits | User prompted to confirm before fetching |
| Non-interactive session (piped/EOF) | Confirmation defaults to `N`; aborts |
| Filename collision | Resolved by appending `_1`, `_2`, … |

---

## Dependencies

| Package | Purpose |
|---|---|
| [Biopython](https://biopython.org/) | Entrez API access (`Bio.Entrez`), GenBank parsing (`Bio.SeqIO`) |

Python standard library only otherwise — no additional dependencies.

---

## Licence

MIT
