# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Script that queries the InspireHEP REST API for an author's publications, categorizes them, and outputs BibTeX files for use in the LaTeX CV project at `../ovlf_publication_list/`.

## Dependencies

```bash
python -m pip install requests
```

## Running

```bash
python inspirehep_papers.py                  # write .bib files to ../ovlf_publication_list/
python inspirehep_papers.py --dry-run        # show categorization without writing
python inspirehep_papers.py --verbose        # print each record's categorization
python inspirehep_papers.py --author Smith   # query a different author
python inspirehep_papers.py --output-dir /path/to/dir
```

## Architecture

`inspirehep_papers.py` is the entire codebase. It makes two API calls to `https://inspirehep.net/api/literature`:

1. **JSON call** — fetches metadata (texkeys, document_type, collaborations, publication_info, first author) for categorization
2. **BibTeX call** — fetches ready-made BibTeX entries for all records

### Categorization rules (in priority order)

1. Thesis → skipped (kept manually in the LaTeX project)
2. IceCube/TA collaboration conference proceedings → `pub_collab_proceedings.bib` (not included in CV), **unless** first author is Fedynitch, Prosekin, Hymon, or Fujisue (those stay in `pub_proc.bib`)
3. Other conference papers or proceedings journals (PoS, EPJ Web Conf., etc.) → `pub_proc.bib`
4. Telescope Array collaboration → `pub_ta_journals.bib`
5. IceCube collaboration → `pub_icecube_journals.bib`
6. Everything else → `pub_journals.bib` (few-author papers)
7. Any of the above without a journal (unpublished preprints) → `pub_unpublished.bib`

### Key configuration

- `PROCEEDINGS_JOURNALS` — set of journal names that indicate proceedings
- `CATEGORY_OVERRIDES` — manual texkey→category overrides for papers INSPIRE doesn't tag correctly (e.g., TA papers missing collaboration metadata)
- `OWN_PROCEEDINGS_AUTHORS` — first-author surnames whose collaboration proceedings stay in the proceedings section

### Output files

| File | Content | In CV? |
|------|---------|--------|
| `pub_journals.bib` | Few-author journal articles | Yes |
| `pub_icecube_journals.bib` | IceCube collaboration journal articles | Yes |
| `pub_ta_journals.bib` | Telescope Array journal articles | Yes |
| `pub_proc.bib` | Own conference proceedings | Yes |
| `pub_collab_proceedings.bib` | IceCube/TA collaboration proceedings | No |
| `pub_unpublished.bib` | Preprints without journal | No |
| `pub_thesis.bib` | Not touched by this script | Yes |
