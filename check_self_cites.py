import requests
import time
from urllib.parse import quote_plus

# === USER INPUT ================================================================
DOIS = [
    # Put your target paper DOIs here
    "10.1103/PhysRevD.100.103018",
    "10.1103/PhysRevD.107.123037",
    "10.1103/PhysRevD.102.063002",
    "10.3847/1538-4357/acaf5f",
    "10.3847/1538-4357/ac5027"
    # "10.xxxx/xxxxx",
]

# Identify *you* in author lists. Prefer an INSPIRE BAI or author record ID if you know it.
MY_NAME_PATTERNS = {
    # Any of these (case-insensitive substring match) will flag "you" in a citing paper's author list
    "Fedynitch, Anatoli",
    "A. Fedynitch",
    # add more variants if needed
}
# If you know your INSPIRE author "BAI" like "A.Fedynitch.1", add it here to match by ID as well.
MY_INSPIRE_BAI = "A.Fedynitch.1"  # e.g., "A.Fedynitch.1"

# Timeout / rate limit handling
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "inspire-selfcite-filter/1.0"})

def get_json(url, retries=5):
    for i in range(retries):
        r = SESSION.get(url, timeout=30)
        if r.status_code == 429:  # rate limited
            time.sleep(5 + i)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Failed after {retries} tries: {url}")

def resolve_doi_to_record(doi):
    url = f"https://inspirehep.net/api/doi/{quote_plus(doi)}"
    data = get_json(url)
    md = data.get("metadata", {})
    recid = md.get("control_number") or data.get("id")
    title = (md.get("titles") or [{}])[0].get("title", "(no title)")
    return recid, title

def iter_citing_records(target_recid, fields=(
    "authors.full_name,authors.ids,control_number,titles,earliest_date"
)):
    # We search for *citing* papers using 'refersto:recid:<ID>'
    base = "https://inspirehep.net/api/literature"
    q = f"refersto:recid:{target_recid}"
    url = f"{base}?size=1000&fields={fields}&q={quote_plus(q)}"
    while url:
        data = get_json(url)
        for hit in data.get("hits", {}).get("hits", []):
            yield hit.get("metadata", {})
        url = data.get("links", {}).get("next")

def author_matches_me(author_obj):
    # 1) Match by INSPIRE BAI if available
    if MY_INSPIRE_BAI:
        for idobj in author_obj.get("ids", []):
            # schema/value may vary; match by value anywhere
            val = (idobj.get("value") or "").lower()
            if MY_INSPIRE_BAI.lower() in val:
                return True
    # 2) Fallback: fuzzy string match on full_name
    full = (author_obj.get("full_name") or "").lower()
    for pat in MY_NAME_PATTERNS:
        if pat.lower() in full:
            return True
    return False

def is_smallteam_self_cite(citing_md):
    authors = citing_md.get("authors") or []
    # treat unknown author lists as "not small team" to avoid false exclusions
    if not authors:
        return False
    if len(authors) >= 10:
        return False
    return any(author_matches_me(a) for a in authors)

def count_citations_excluding_smallteam_self(doi):
    recid, title = resolve_doi_to_record(doi)
    total = 0
    excluded = 0
    kept_examples = []
    dropped_examples = []
    for citing in iter_citing_records(recid):
        total += 1
        if is_smallteam_self_cite(citing):
            excluded += 1
            if len(dropped_examples) < 3:
                dropped_examples.append({
                    "title": (citing.get("titles") or [{}])[0].get("title", ""),
                    "recid": citing.get("control_number"),
                })
        else:
            if len(kept_examples) < 3:
                kept_examples.append({
                    "title": (citing.get("titles") or [{}])[0].get("title", ""),
                    "recid": citing.get("control_number"),
                })
    included = total - excluded
    return {
        "doi": doi,
        "title": title,
        "recid": recid,
        "total_citations_found": total,
        "excluded_smallteam_self": excluded,
        "included_after_filter": included,
        "kept_examples": kept_examples,
        "dropped_examples": dropped_examples,
    }

if __name__ == "__main__":
    results = []
    for doi in DOIS:
        try:
            res = count_citations_excluding_smallteam_self(doi)
        except Exception as e:
            res = {"doi": doi, "error": str(e)}
        results.append(res)

    # Pretty print
    for r in results:
        if "error" in r:
            print(f"[ERROR] {r['doi']}: {r['error']}")
            continue
        print("\n" + "="*80)
        print(f"Title : {r['title']}")
        print(f"DOI   : {r['doi']}")
        print(f"recid : {r['recid']}")
        print(f"Total citing papers           : {r['total_citations_found']}")
        print(f"Excluded (<10 authors & me)   : {r['excluded_smallteam_self']}")
        print(f"Included after custom filter  : {r['included_after_filter']}")
        if r["dropped_examples"]:
            print("  Dropped examples:")
            for ex in r["dropped_examples"]:
                print(f"    - {ex['title']} (recid {ex['recid']})")
        if r["kept_examples"]:
            print("  Kept examples:")
            for ex in r["kept_examples"]:
                print(f"    - {ex['title']} (recid {ex['recid']})")
