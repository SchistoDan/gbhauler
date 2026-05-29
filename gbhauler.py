#!/usr/bin/env python3
"""
gbhauler.py — Bulk GenBank record retrieval via NCBI Entrez
==========================================================

Fetch GenBank records from NCBI using accession numbers, GI numbers, or a
full Entrez search string.  Writes one .gb file per record and a tab-separated
summary of query IDs, accessions, and titles.
"""

import argparse
import logging
import re
import sys
import time
from pathlib import Path

from Bio import Entrez, SeqIO


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TITLE_MAX_LEN       = 80    # Max characters for title-based filenames
RETRY_LIMIT         = 3     # Retries per record on transient errors
RETRY_DELAY         = 5     # Seconds between retries
LARGE_RESULT_THRESH = 1000  # Prompt for confirmation above this hit count
ESEARCH_BATCH       = 500   # UIDs to retrieve per esearch page (WebEnv paging)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(verbose: bool) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    fmt   = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(format=fmt, datefmt="%Y-%m-%d %H:%M:%S", level=level)
    return logging.getLogger("gbhaul")


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------
def sanitise_filename(name: str, max_len: int = TITLE_MAX_LEN) -> str:
    """Replace forbidden/whitespace characters with underscores and truncate."""
    clean = re.sub(r'[\s/\\:*?"<>|]+', "_", name)
    clean = re.sub(r'_+', "_", clean).strip("_")
    if len(clean) > max_len:
        clean = clean[:max_len].rstrip("_")
    return clean or "unnamed"


# ---------------------------------------------------------------------------
# Input: accession/GI list from file and/or --ids
# ---------------------------------------------------------------------------
def load_ids(args) -> list[str]:
    """Return a deduplicated list of IDs from --ids and/or --input."""
    ids = []

    if args.ids:
        for item in args.ids.split(","):
            item = item.strip()
            if item:
                ids.append(item)

    if args.input:
        path = Path(args.input)
        if not path.is_file():
            sys.exit(f"[ERROR] Input file not found: {args.input}")
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                for item in line.split(","):
                    item = item.strip()
                    if item:
                        ids.append(item)

    # Deduplicate while preserving order
    seen, unique = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            unique.append(i)

    return unique


# ---------------------------------------------------------------------------
# Input: NCBI search string → list of UIDs
# ---------------------------------------------------------------------------
def resolve_search_query(query: str, db: str, email: str,
                         api_key: str | None,
                         log: logging.Logger) -> list[str]:
    """
    Run esearch for `query` against `db`, page through WebEnv history,
    and return the full list of UIDs.  Prompts for confirmation if the
    hit count exceeds LARGE_RESULT_THRESH.
    """
    Entrez.email   = email
    Entrez.api_key = api_key

    log.info("Running esearch: db=%s  query=%s", db, query)

    # First call: get count + WebEnv cookie (usehistory="y")
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            with Entrez.esearch(db=db, term=query,
                                usehistory="y", retmax=0) as sh:
                result = Entrez.read(sh)
            break
        except Exception as exc:
            log.warning("esearch attempt %d/%d failed: %s", attempt, RETRY_LIMIT, exc)
            if attempt == RETRY_LIMIT:
                sys.exit("[ERROR] esearch failed after all retries — aborting.")
            time.sleep(RETRY_DELAY)

    count     = int(result["Count"])
    webenv    = result["WebEnv"]
    query_key = result["QueryKey"]

    log.info("esearch returned %d hit(s).", count)

    if count == 0:
        log.warning("No records matched the search query — nothing to fetch.")
        return []

    # Large-result confirmation gate
    if count > LARGE_RESULT_THRESH:
        print(
            f"\n !!! Your search matched {count:,} records, which exceeds the "
            f"confirmation threshold of {LARGE_RESULT_THRESH:,}. !!! \n"
            f"  Fetching all {count:,} records may take a long time and generate "
            f"significant output.\n"
        )
        try:
            answer = input("  Continue? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes"):
            sys.exit("Aborted by user.")
        print()

    # Page through UIDs using WebEnv history
    all_uids: list[str] = []
    retstart = 0

    while retstart < count:
        for attempt in range(1, RETRY_LIMIT + 1):
            try:
                with Entrez.esearch(
                    db=db, term=query,
                    usehistory="y",
                    WebEnv=webenv, query_key=query_key,
                    retstart=retstart, retmax=ESEARCH_BATCH,
                ) as sh:
                    page = Entrez.read(sh)
                all_uids.extend(page["IdList"])
                log.debug("Paged UIDs %d–%d of %d.",
                          retstart + 1,
                          min(retstart + ESEARCH_BATCH, count),
                          count)
                break
            except Exception as exc:
                log.warning("UID page attempt %d/%d failed: %s",
                            attempt, RETRY_LIMIT, exc)
                if attempt == RETRY_LIMIT:
                    sys.exit("[ERROR] Could not retrieve UID page — aborting.")
                time.sleep(RETRY_DELAY)

        retstart += ESEARCH_BATCH
        time.sleep(0.11 if api_key else 0.34)

    log.info("Retrieved %d UID(s) from search.", len(all_uids))
    return all_uids


# ---------------------------------------------------------------------------
# Filename stem selection
# ---------------------------------------------------------------------------
def choose_stem(record, query_id: str, mode: str, log: logging.Logger) -> str:
    """
    Return a filename stem (no extension) based on the naming mode:
      accession — record.id (accession.version)
      gi        — GI number from annotations or dbxrefs; falls back to accession
      title     — sanitised record.description; falls back to accession
    """
    if mode == "accession":
        return sanitise_filename(record.id)

    elif mode == "gi":
        gi = record.annotations.get("gi", "")
        if not gi:
            for xref in record.dbxrefs:
                if xref.startswith("GI:"):
                    gi = xref.split(":", 1)[1]
                    break
        if gi:
            return sanitise_filename(str(gi))
        log.warning("GI not found for %s — falling back to accession.", query_id)
        return sanitise_filename(record.id)

    elif mode == "title":
        title = record.description.strip()
        if title and title.lower() != "no definition line found":
            return sanitise_filename(title)
        log.warning("No usable title for %s — falling back to accession.", query_id)
        return sanitise_filename(record.id)

    return sanitise_filename(record.id)


# ---------------------------------------------------------------------------
# Fetch a single record by UID / accession / GI
# ---------------------------------------------------------------------------
def fetch_record(query_id: str, db: str, email: str,
                 api_key: str | None, log: logging.Logger):
    """
    Fetch one GenBank record.  For accession/GI mode the ID is first
    resolved via esearch; for search mode the UID is passed directly.
    Returns a SeqRecord or None on failure.
    """
    Entrez.email   = email
    Entrez.api_key = api_key

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            log.debug("Fetching '%s' (attempt %d)…", query_id, attempt)

            # If the query_id looks like a bare integer it is already a UID;
            # otherwise run esearch to resolve it first.
            if re.fullmatch(r'\d+', query_id):
                uid = query_id
            else:
                with Entrez.esearch(db=db, term=query_id, retmax=1) as sh:
                    search_result = Entrez.read(sh)
                id_list = search_result.get("IdList", [])
                if not id_list:
                    log.warning("No record found for '%s' — skipping.", query_id)
                    return None
                uid = id_list[0]
                log.debug("Resolved '%s' → UID %s", query_id, uid)

            with Entrez.efetch(db=db, id=uid,
                               rettype="gb", retmode="text") as fh:
                record = SeqIO.read(fh, "genbank")

            return record

        except Exception as exc:
            log.warning("Error fetching '%s' (attempt %d/%d): %s",
                        query_id, attempt, RETRY_LIMIT, exc)
            if attempt < RETRY_LIMIT:
                log.info("Retrying in %d s…", RETRY_DELAY)
                time.sleep(RETRY_DELAY)

    log.error("Failed to retrieve '%s' after %d attempts — skipping.",
              query_id, RETRY_LIMIT)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="gbhaul",
        description=(
            "gbhaul — bulk GenBank record retrieval via NCBI Entrez.\n\n"
            "Input modes (combinable):\n"
            "  --input FILE      file of accession/GI numbers\n"
            "  --ids A,B,C       comma-delimited accession/GI numbers\n"
            "  --search 'QUERY'  NCBI Entrez search string\n\n"
            "Writes one .gb file per record and a combined summary TSV.\n\n"
            "For full documentation run: python gbhaul.py --help-full"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ---- Input --------------------------------------------------------------
    input_grp = parser.add_argument_group(
        "Input (at least one of --input, --ids, or --search is required)"
    )
    input_grp.add_argument(
        "-i", "--input",
        metavar="FILE",
        help=(
            "Path to a plain-text file of accession/GI numbers. "
            "One ID per line; comma-separated values on a single line are also "
            "accepted. Lines beginning with '#' are ignored."
        ),
    )
    input_grp.add_argument(
        "--ids",
        metavar="ID[,ID,…]",
        help=(
            "Comma-delimited accession/GI numbers supplied directly on the "
            "command line. Mixed types are supported, e.g.: "
            "AY123456,NM_001234.1,229639"
        ),
    )
    input_grp.add_argument(
        "--search",
        metavar="QUERY",
        help=(
            "A valid NCBI Entrez search string. The script runs esearch, pages "
            "through all returned UIDs, and fetches each record — no intermediate "
            "ID list required. Results are merged with any --input/--ids records "
            "and deduplicated. If the search returns >1,000 hits, confirmation is "
            "required before fetching proceeds. "
            "Example: \"txid229639[Organism:exp] AND mitochondrion[filter]\""
        ),
    )

    # ---- Output -------------------------------------------------------------
    out_grp = parser.add_argument_group("Output")
    out_grp.add_argument(
        "-o", "--outdir",
        metavar="DIR",
        default=".",
        help="Directory for output files. Created if it does not exist. (default: .)",
    )
    out_grp.add_argument(
        "--name-by",
        metavar="MODE",
        choices=["accession", "gi", "title"],
        default="accession",
        help=(
            "Filename convention for individual .gb files. "
            "accession: <accession.version>.gb (default); "
            "gi: <GI_number>.gb (falls back to accession if GI absent); "
            "title: <sanitised_record_title>.gb, truncated to 80 characters "
            "with unsafe characters replaced by underscores "
            "(falls back to accession if title is absent)."
        ),
    )
    out_grp.add_argument(
        "--summary",
        metavar="FILE",
        default="gbhaul_summary.tsv",
        help=(
            "Filename for the summary TSV (written inside --outdir). "
            "Columns: query_id, accession, title. (default: gbhaul_summary.tsv)"
        ),
    )

    # ---- Entrez -------------------------------------------------------------
    entrez_grp = parser.add_argument_group("NCBI Entrez")
    entrez_grp.add_argument(
        "--email",
        required=True,
        metavar="EMAIL",
        help=(
            "Email address to identify yourself to NCBI — required by NCBI "
            "policy for all Entrez API use."
        ),
    )
    entrez_grp.add_argument(
        "--api-key",
        metavar="KEY",
        default=None,
        help=(
            "NCBI API key. Optional, but raises the rate limit from ~3 to ~10 "
            "requests/second and is strongly recommended for large batches. "
            "Obtain a free key at https://www.ncbi.nlm.nih.gov/account/"
        ),
    )
    entrez_grp.add_argument(
        "--db",
        metavar="DATABASE",
        default="nucleotide",
        help=(
            "NCBI Entrez database to query. Applied to all input modes. "
            "Common values: nucleotide (default), protein, nuccore, gene."
        ),
    )

    # ---- Misc ---------------------------------------------------------------
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging (shows UID resolution, paging detail, etc.).",
    )

    args = parser.parse_args()

    # -------------------------------------------------------------------------
    log = setup_logging(args.verbose)

    if not args.input and not args.ids and not args.search:
        parser.error(
            "Provide at least one input source: "
            "--input FILE, --ids ID[,ID,…], or --search 'QUERY'."
        )

    # --- Collect all UIDs / IDs to fetch -------------------------------------

    # 1. Accession/GI list sources
    direct_ids = load_ids(args)
    if direct_ids:
        log.info("Loaded %d unique ID(s) from --input/--ids.", len(direct_ids))

    # 2. Search string source
    search_uids: list[str] = []
    if args.search:
        search_uids = resolve_search_query(
            args.search, args.db, args.email, args.api_key, log
        )

    # Merge: direct IDs first, then search UIDs; deduplicate preserving order
    all_ids = direct_ids + search_uids
    seen, unique_ids = set(), []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            unique_ids.append(i)

    if not unique_ids:
        sys.exit("[ERROR] No records to fetch after resolving all inputs.")

    log.info("Total unique records to fetch: %d", len(unique_ids))

    # ---- Output setup -------------------------------------------------------
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summary_path  = outdir / args.summary
    summary_lines: list[tuple[str, str, str]] = []

    delay    = 0.11 if args.api_key else 0.34
    fetched  = 0
    skipped  = 0

    # ---- Fetch loop ---------------------------------------------------------
    for query_id in unique_ids:
        record = fetch_record(query_id, args.db, args.email, args.api_key, log)

        if record is None:
            skipped += 1
            time.sleep(delay)
            continue

        stem    = choose_stem(record, query_id, args.name_by, log)
        gb_path = outdir / f"{stem}.gb"

        # Collision handling
        if gb_path.exists():
            counter = 1
            while gb_path.exists():
                gb_path = outdir / f"{stem}_{counter}.gb"
                counter += 1
            log.warning("Filename collision — writing to %s instead.", gb_path.name)

        with open(gb_path, "w") as out_fh:
            SeqIO.write(record, out_fh, "genbank")
        log.info("[%d/%d] Saved: %s", fetched + skipped + 1, len(unique_ids), gb_path.name)

        title = record.description.strip() or "N/A"
        summary_lines.append((query_id, record.id, title))

        fetched += 1
        time.sleep(delay)

    # ---- Summary TSV --------------------------------------------------------
    with open(summary_path, "w") as sf:
        sf.write("query_id\taccession\ttitle\n")
        for row in summary_lines:
            sf.write("\t".join(row) + "\n")

    log.info("Summary written: %s", summary_path)
    log.info(
        "Done.  Fetched: %d  |  Skipped: %d  |  Total: %d",
        fetched, skipped, len(unique_ids),
    )

    if skipped:
        sys.exit(1)  # Non-zero exit for pipeline/caller awareness


if __name__ == "__main__":
    main()
