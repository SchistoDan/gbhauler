# gbhauler :truck: - **Bulk GenBank record retrieval via NCBI Entrez**

gbhauler fetches GenBank records from NCBI using accession numbers, GI numbers, or a full Entrez search string. It writes one `.gb` file per record and a tab-separated summary of query IDs, accessions, and titles — with sensible defaults, flexible filename conventions, and robust retry/error handling throughout.


---


## Installation
gbhauler requires Python 3.10+ and [Biopython](https://biopython.org/).

```bash
pip install biopython
# Or
conda install conda-forge::biopython
```

Then clone or download `gbhauler.py` and run it directly. No further installation needed.
```bash
git clone https://github.com/your-org/gbhauler.git
cd gbhauler
python gbhauler.py --help
```


---


## Quick start

```bash
# Fetch records from an accession list file
python gbhauler.py --email you@example.com -i accessions.txt -o ./genbank_out

# Fetch a few IDs directly from the command line
python gbhauler.py --email you@example.com --ids "AY123456,NM_001234.1,229639" -o ./out

# Use an Entrez search string to find and fetch records automatically
python gbhauler.py --email you@example.com \
    --search "txid229639[Organism:exp] AND mitochondrion[filter]" \
    -o ./mito_records
```


---


## Full argument usage
```
usage: gbhauler [-h] [-i FILE] [--ids ID[,ID,…]] [--search QUERY]
              [-o DIR] [--name-by MODE] [--summary FILE]
              --email EMAIL [--api-key KEY] [--db DATABASE] [-v]
```

### Input
> **At least one of `--input`, `--ids`, or `--search` is required  (more information below).**
```
-i, --input FILE          [optional]
    Path to a file of accession/GI numbers. One per line; comma-separated
    values accepted. Lines starting with '#' ignored.
 
--ids ID[,ID,...]         [optional]
    Comma-delimited accession/GI numbers supplied directly on the command
    line. Mixed types (accession, GI) supported.
 
--search QUERY            [optional]
    NCBI Entrez search string. Results are fetched in addition to any
    --input/--ids records and deduplicated.
```
 
### Output
```
-o, --outdir DIR          [optional]  (default: .)
    Output directory. Created if it does not exist.
 
--name-by MODE            [optional]  (default: accession)
    Filename convention for individual .gb files.
    Choices: accession | gi | title
 
--summary FILE            [optional]  (default: gbhaul_summary.tsv)
    Name of the summary TSV, written inside --outdir.
```
 
### NCBI Entrez
```
--email EMAIL             [required]
    Your email address, required by NCBI policy for all Entrez API use.
 
--api-key KEY             [optional]
    NCBI API key. Raises the rate limit from ~3 to ~10 req/s. Recommended
    for large batches. Obtain one free at: https://www.ncbi.nlm.nih.gov/account/
 
--db DATABASE             [optional]  (default: nucleotide)
    Entrez database to query.
    Common options: nucleotide | protein | nuccore | gene
```
 
### Miscellaneous
```
-v, --verbose             [optional]
    Enable debug-level logging (UID resolution, paging detail, retry attempts).
```


---


## Input modes
All three modes (`--input`, `--ids`, `--search`) can be combined in a single run (if desired). When more than one mode is used, IDs are merged and deduplicated in the order `--input` → `--ids` → `--search`.

### `--input FILE`
A plain-text file of GenBank accession numbers or GI numbers, one per line. Comma-separated values on a single line are also accepted. Lines beginning with `#` are ignored.
```
# COI sequences — Schistosoma japonicum
AY123456
NM_001234.1
229639, AY999999
```

### `--ids ID[,ID,...]`
A comma-delimited list of accession/GI numbers supplied directly on the command line. Mixes of accession and GI numbers is supported.
```bash
--ids "AY123456,NM_001234.1,229639"
```

### `--search "QUERY"`
Any valid [NCBI Entrez search string](https://www.ncbi.nlm.nih.gov/books/NBK3837/). gbhauler runs `esearch` with WebEnv history, pages through all matching UIDs in batches of 500, then fetches each record via `efetch`. Therefore, no intermediate ID list is required. An NCBI search string can be manually created through an initial search on [the web portal](https://www.ncbi.nlm.nih.gov/nuccore) - see 'search details' on the right-hand side for the search string.
```bash
--search "txid229639[Organism:exp] AND (mitochondrion[filter] AND (\"500\"[SLEN]:\"500000\"[SLEN]))"
```

> **Large result sets:** if a search returns more than 1,000 records, gbhauler will print the hit count and prompt for confirmation (Y/N) before proceeding.


---


## Output
For each successfully retrieved record gbhauler writes a GenBank flat-file:
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

> Title-based filenames have whitespace and filesystem-unsafe characters (`/ \ : * ? " < > |`) replaced with underscores and are truncated to 80 characters. Filename collisions across any mode are resolved by appending `_1`, `_2`, and so on.


---


## Examples

**Fetch GenBank entries from those listed in a file, with accession-named outputs (default):**
```bash
python gbhauler.py \
    --email you@example.com \
    -i accessions.txt \
    -o ./genbank_out
```

**Fetch three GenBnk entries using a comman-seperated list of mixed IDs, with title-named outputs:**
```bash
python gbhauler.py \
    --email you@example.com \
    --ids "AY123456,NM_001234.1,229639" \
    --name-by title \
    -o ./out
```

**Conduct an Entrez search for all mitochondrial GenBank entries for a taxa, with API key supplied for improved speed:**
```bash
python gbhauler.py \
    --email you@example.com \
    --api-key YOUR_NCBI_KEY \
    --search "txid229639[Organism:exp] AND mitochondrion[filter]" \
    --name-by accession \
    -o ./mito_records
```

**Conduct an Entrez search for all complete _Schistosoma japonicum_ entries in the NCBI Protein database, with two additional specified `--ids` and outputs named by their GI number:
```bash
python gbhauler.py \
    --email you@example.com \
    --api-key YOUR_NCBI_KEY \
    --db protein \
    --search "Schistosoma japonicum[Organism] AND complete[Title]" \
    --ids "AAB12345,CAA99999" \
    --name-by gi \
    --summary sj_proteins.tsv \
    -o ./out
```


---


## NCBI usage policy

NCBI requires that all Entrez API users identify themselves with a valid email address via `--email`. For bulk queries, obtaining a free [NCBI API key](https://www.ncbi.nlm.nih.gov/account/) is strongly recommended as it raises the allowed request rate from 3 to 10 per second, and reduces the chance of temporary blocks during large runs. Please review [NCBI's usage guidelines](https://www.ncbi.nlm.nih.gov/home/about/policies/) before running large batch jobs.


---


## Licence

MIT
> Created by Dan Parsons @NHMUK
