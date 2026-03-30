"""Fetch publications from InspireHEP and generate categorized BibTeX files."""

import argparse
import re
import sys
import time
from pathlib import Path

import requests

INSPIRE_API = "https://inspirehep.net/api/literature"

# Journals that indicate conference proceedings even if document_type doesn't say so
PROCEEDINGS_JOURNALS = {
    "PoS",
    "EPJ Web Conf.",
    "Nucl. Part. Phys. Proc.",
}

OUTPUT_FILES = {
    "journals": "pub_journals.bib",
    "icecube": "pub_icecube_journals.bib",
    "ta": "pub_ta_journals.bib",
    "proceedings": "pub_proc.bib",
    "unpublished": "pub_unpublished.bib",
    "collab_proceedings": "pub_collab_proceedings.bib",
}

# Manual overrides for papers that INSPIRE doesn't tag with the right collaboration
CATEGORY_OVERRIDES = {
    "Kieu:2024uem": "ta",        # TA paper, no collaboration tag in INSPIRE
    "Abbasi:2023swr": "ta",      # TA paper, no collaboration tag in INSPIRE
}

# IceCube/TA proceedings are filed under the collaboration, not proceedings,
# UNLESS one of these people is the first author (= group member's own proceeding)
OWN_PROCEEDINGS_AUTHORS = {"Fedynitch", "Prosekin", "Hymon", "Fujisue"}


def fetch_with_retry(url, params=None, headers=None, max_retries=5):
    """GET request with exponential backoff on rate limits and server errors."""
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, headers=headers, timeout=120)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 500, 502, 503):
            wait = 2 ** attempt
            print(f"  HTTP {resp.status_code}, retrying in {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    resp.raise_for_status()


def fetch_json_metadata(author, max_results):
    """Fetch record metadata from InspireHEP as JSON."""
    print(f"Fetching JSON metadata for author '{author}'...")
    params = {
        "q": f"a {author}",
        "size": max_results,
        "sort": "mostrecent",
        "fields": "texkeys,document_type,collaborations,publication_info,authors.full_name",
    }
    resp = fetch_with_retry(INSPIRE_API, params=params)
    data = resp.json()
    total = data["hits"]["total"]
    records = [hit["metadata"] for hit in data["hits"]["hits"]]
    print(f"  Got {len(records)} records (total in INSPIRE: {total})")
    if total > max_results:
        print(f"  WARNING: {total} records exist but only {max_results} fetched. "
              f"Increase --max-results to get all.")
    return records


def fetch_bibtex_bulk(author, max_results):
    """Fetch all matching records as a single BibTeX string."""
    print(f"Fetching BibTeX entries...")
    params = {
        "q": f"a {author}",
        "size": max_results,
        "sort": "mostrecent",
        "format": "bibtex",
    }
    resp = fetch_with_retry(INSPIRE_API, params=params)
    text = resp.text
    # Replace Unicode/LaTeX characters that require amssymb
    text = text.replace("★", r"$\star$")
    text = text.replace(r"\bigstar", r"\star")
    print(f"  Got {len(text)} bytes of BibTeX")
    return text


def parse_bibtex_entries(bibtex_text):
    """Split concatenated BibTeX into a dict of {texkey: entry_string}."""
    entries = {}
    # Match @type{key, ... } blocks — the closing } must be at the start of a line
    pattern = re.compile(r"(@\w+\{(.+?),\s*\n.*?\n\})", re.DOTALL)
    for match in pattern.finditer(bibtex_text):
        full_entry = match.group(1)
        texkey = match.group(2).strip()
        entries[texkey] = full_entry
    return entries


def is_published(metadata):
    """Check if a record is published (has a real journal, not just arXiv)."""
    pub_info_list = metadata.get("publication_info", [])
    if not pub_info_list:
        return False
    journal = pub_info_list[0].get("journal_title", "")
    return bool(journal)


def get_first_author_surname(metadata):
    """Extract the surname of the first author."""
    authors = metadata.get("authors", [])
    if not authors:
        return ""
    # INSPIRE format: "Surname, FirstName" or just "Surname"
    full_name = authors[0].get("full_name", "")
    return full_name.split(",")[0].strip()


def is_collab_proceeding(doc_types, journal, collabs):
    """Check if this is a conference proceeding from IceCube or TA."""
    is_proceeding = "conference paper" in doc_types or journal in PROCEEDINGS_JOURNALS
    is_collab = (any("Telescope Array" in c for c in collabs)
                 or any("IceCube" in c for c in collabs))
    return is_proceeding and is_collab


def categorize_record(metadata):
    """Categorize a record. Returns (category, published) or (None, False) to skip."""
    doc_types = set(metadata.get("document_type", []))
    collabs = {c["value"] for c in metadata.get("collaborations", [])}
    pub_info_list = metadata.get("publication_info", [])
    journal = pub_info_list[0].get("journal_title", "") if pub_info_list else ""
    published = is_published(metadata)
    first_author = get_first_author_surname(metadata)

    # Rule 1: thesis -> skip entirely
    if "thesis" in doc_types:
        return None, False

    # Rule 2: IceCube/TA collaboration proceedings -> separate file (not in CV),
    # unless the first author is a group member (keep those in proceedings)
    if is_collab_proceeding(doc_types, journal, collabs):
        if first_author in OWN_PROCEEDINGS_AUTHORS:
            return "proceedings", published
        return "collab_proceedings", published

    # Rule 3: other conference papers -> proceedings
    if "conference paper" in doc_types:
        return "proceedings", published

    # Rule 3b: journal-name fallback for proceedings
    if journal in PROCEEDINGS_JOURNALS:
        return "proceedings", published

    # Rule 4: Telescope Array (checked before IceCube so joint papers go to TA)
    if any("Telescope Array" in c for c in collabs):
        return "ta", published

    # Rule 5: IceCube collaboration
    if any("IceCube" in c for c in collabs):
        return "icecube", published

    # Rule 6: everything else -> few-author journals
    return "journals", published


def get_texkey(metadata):
    """Extract the primary texkey from a record's metadata."""
    texkeys = metadata.get("texkeys", [])
    return texkeys[0] if texkeys else None


def main():
    parser = argparse.ArgumentParser(
        description="Fetch publications from InspireHEP and generate BibTeX files"
    )
    parser.add_argument("--author", default="Fedynitch",
                        help="Author name for INSPIRE query (default: Fedynitch)")
    parser.add_argument("--output-dir",
                        default=str(Path(__file__).resolve().parent.parent / "ovlf_publication_list"),
                        help="Output directory for .bib files")
    parser.add_argument("--max-results", type=int, default=1000,
                        help="Maximum number of results to fetch (default: 1000)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show categorization without writing files")
    parser.add_argument("--verbose", action="store_true",
                        help="Print each record's categorization")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        print(f"Error: output directory '{output_dir}' does not exist", file=sys.stderr)
        sys.exit(1)

    # Fetch data from InspireHEP
    records = fetch_json_metadata(args.author, args.max_results)
    time.sleep(0.5)  # small delay between API calls
    bibtex_text = fetch_bibtex_bulk(args.author, args.max_results)
    bibtex_entries = parse_bibtex_entries(bibtex_text)
    print(f"  Parsed {len(bibtex_entries)} BibTeX entries")

    # Categorize records and collect BibTeX entries
    categorized = {cat: [] for cat in OUTPUT_FILES}
    counts = {cat: 0 for cat in OUTPUT_FILES}
    counts.update({"skipped": 0, "unmatched": 0})
    unmatched = []

    for record in records:
        texkey = get_texkey(record)
        category, published = categorize_record(record)

        # Apply manual overrides
        if texkey in CATEGORY_OVERRIDES:
            category = CATEGORY_OVERRIDES[texkey]

        if category is None:
            counts["skipped"] += 1
            if args.verbose:
                print(f"  SKIP (thesis): {texkey}")
            continue

        if texkey and texkey in bibtex_entries:
            # Unpublished papers go to unpublished.bib regardless of category
            if published:
                target = category
            else:
                target = "unpublished"
            categorized[target].append(bibtex_entries[texkey])
            counts[target] += 1
            if args.verbose:
                pub_info = record.get("publication_info", [{}])
                journal = pub_info[0].get("journal_title", "") if pub_info else ""
                collabs = [c["value"] for c in record.get("collaborations", [])]
                collab_str = f" [{', '.join(collabs)}]" if collabs else ""
                pub_str = "" if published else " [UNPUBLISHED]"
                print(f"  {target:12s}: {texkey}{collab_str}  ({journal}){pub_str}")
        else:
            counts["unmatched"] += 1
            unmatched.append(texkey or "(no texkey)")
            if args.verbose:
                print(f"  UNMATCHED: {texkey}")

    # Summary
    print(f"\nCategorization summary:")
    print(f"  Few-author journals:  {counts['journals']:4d}  -> {OUTPUT_FILES['journals']}")
    print(f"  IceCube collaboration:{counts['icecube']:4d}  -> {OUTPUT_FILES['icecube']}")
    print(f"  Telescope Array:      {counts['ta']:4d}  -> {OUTPUT_FILES['ta']}")
    print(f"  Conference proceedings:{counts['proceedings']:4d}  -> {OUTPUT_FILES['proceedings']}")
    print(f"  Collab. proceedings:  {counts['collab_proceedings']:4d}  -> {OUTPUT_FILES['collab_proceedings']} (not in CV)")
    print(f"  Unpublished:          {counts['unpublished']:4d}  -> {OUTPUT_FILES['unpublished']} (not in CV)")
    print(f"  Thesis (skipped):     {counts['skipped']:4d}")
    print(f"  Unmatched (no bibtex):{counts['unmatched']:4d}")

    if unmatched:
        print(f"\nUnmatched texkeys:")
        for tk in unmatched:
            print(f"  - {tk}")

    # Write files
    if args.dry_run:
        print("\n--dry-run: no files written")
    else:
        for category, filename in OUTPUT_FILES.items():
            filepath = output_dir / filename
            entries = categorized[category]
            with open(filepath, "w") as f:
                f.write("\n\n".join(entries))
                if entries:
                    f.write("\n")
            print(f"Wrote {len(entries)} entries to {filepath}")


if __name__ == "__main__":
    main()
