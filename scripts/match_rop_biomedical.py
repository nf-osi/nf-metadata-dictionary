#!/usr/bin/env python3
"""
Match NF metadata dictionary terms with RoP biomedical CDEs using SapBERT embeddings.

Uses the official rop Python package (pip install rop-biomedical) and the pre-built
FAISS index from Hugging Face (datatecnica/RoP_biomedical, v2026.04).

Requirements:
    pip install rop-biomedical huggingface_hub polars pyarrow

Bundle files (auto-downloaded to --bundle-dir, ~4 GB total):
    elements.parquet   151 MB  — 1.33M CDE records
    embeddings.faiss   3.9 GB  — FAISS IVF4096 similarity index

Usage:
    # Download bundle and run (first run downloads ~4 GB)
    python scripts/match_rop_biomedical.py

    # Use existing bundle directory
    python scripts/match_rop_biomedical.py --bundle-dir /path/to/bundle

    # Slots only, more matches per term
    python scripts/match_rop_biomedical.py --slots-only --top-n 5

    # Lower score threshold (0-1 cosine similarity, default 0.6)
    python scripts/match_rop_biomedical.py --score-cutoff 0.5
"""

import argparse
import csv
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
MODULES_DIR = REPO_ROOT / "modules"
OUTPUT_DIR = REPO_ROOT / "mappings" / "RoP_biomedical"

HF_REPO = "datatecnica/RoP_biomedical"
BUNDLE_VERSION = "v2026.04"
BUNDLE_FILES = ["elements.parquet", "embeddings.faiss"]

_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


# ---------------------------------------------------------------------------
# Extract NF dictionary terms
# ---------------------------------------------------------------------------

def _humanize(name: str) -> str:
    """Split CamelCase and snake_case into space-separated words."""
    name = _CAMEL_RE.sub(" ", name)
    name = name.replace("_", " ")
    return re.sub(r" +", " ", name).strip()


def extract_nf_terms() -> list[dict]:
    """Return list of dicts: name, title, description, source_file, term_type, range, aliases."""
    terms = []
    for path in sorted(MODULES_DIR.rglob("*.yaml")):
        with open(path) as f:
            try:
                doc = yaml.safe_load(f)
            except yaml.YAMLError:
                continue
        if not isinstance(doc, dict):
            continue
        rel = str(path.relative_to(REPO_ROOT))

        for slot_name, slot_def in (doc.get("slots") or {}).items():
            if not isinstance(slot_def, dict):
                continue
            desc = slot_def.get("description") or slot_def.get("comments") or ""
            if isinstance(desc, list):
                desc = " ".join(str(d) for d in desc)
            title = slot_def.get("title") or _humanize(slot_name)
            aliases = slot_def.get("aliases") or []
            terms.append({
                "name": slot_name,
                "title": title,
                "description": str(desc).strip(),
                "source_file": rel,
                "term_type": "slot",
                "range": slot_def.get("range") or "",
                "aliases": "|".join(str(a) for a in aliases),
            })

        for enum_name, enum_def in (doc.get("enums") or {}).items():
            for val_name, val_def in ((enum_def or {}).get("permissible_values") or {}).items():
                val_def = val_def or {}
                desc = val_def.get("description") or ""
                aliases = val_def.get("aliases") or []
                terms.append({
                    "name": val_name,
                    "title": val_name,
                    "description": str(desc).strip(),
                    "source_file": rel,
                    "term_type": f"enum_value:{enum_name}",
                    "range": "",
                    "aliases": "|".join(str(a) for a in aliases),
                })

    return terms


def build_query_text(term: dict) -> str:
    """Compose search text for a term, similar to RoP's compose_search_text."""
    parts = [term["title"]]
    if term["name"] != term["title"]:
        parts.append(_humanize(term["name"]))
    if term["aliases"]:
        parts.extend(a.strip() for a in term["aliases"].split("|") if a.strip())
    if term["description"]:
        parts.append(term["description"])
    return ". ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Bundle download
# ---------------------------------------------------------------------------

def ensure_bundle(bundle_dir: Path) -> dict[str, Path]:
    """Return paths to bundle files, downloading from HF if missing."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    missing = []
    for fname in BUNDLE_FILES:
        p = bundle_dir / fname
        paths[fname] = p
        if not p.exists():
            missing.append(fname)

    if missing:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            sys.exit(
                "huggingface_hub is required to download the bundle.\n"
                "  pip install huggingface_hub\n"
                f"Or manually place {BUNDLE_FILES} in {bundle_dir}"
            )
        for fname in missing:
            print(f"  Downloading {fname} from Hugging Face ({HF_REPO}) …")
            local = hf_hub_download(
                repo_id=HF_REPO,
                filename=f"{BUNDLE_VERSION}/{fname}",
                repo_type="dataset",
                local_dir=str(bundle_dir),
            )
            # hf_hub_download may nest under version subdir; resolve to flat
            downloaded = Path(local)
            flat = bundle_dir / fname
            if downloaded != flat and downloaded.exists():
                downloaded.rename(flat)
            paths[fname] = flat

    return paths


# ---------------------------------------------------------------------------
# Embedding-based matching
# ---------------------------------------------------------------------------

def batch_encode(texts: list[str], config=None) -> "np.ndarray":  # type: ignore[name-defined]
    """Encode a list of query strings using SapBERT. Loads the model once."""
    try:
        from rop.embed import EmbeddingConfig
        from sentence_transformers import SentenceTransformer
        import numpy as np
    except ImportError:
        sys.exit(
            "rop-biomedical is required.\n"
            "  pip install git+https://github.com/datatecnica/RoP_biomedical.git"
        )

    if config is None:
        config = EmbeddingConfig()

    model = SentenceTransformer(config.model_name, device=config.device)
    vectors = model.encode(
        texts,
        batch_size=config.batch_size,
        convert_to_numpy=True,
        normalize_embeddings=config.normalize,
        show_progress_bar=True,
    )
    return vectors.astype("float32", copy=False)  # (N, 768)


def run_matching(
    nf_terms: list[dict],
    bundle_paths: dict[str, Path],
    top_n: int,
    score_cutoff: float,
) -> tuple[list[dict], list[str]]:
    try:
        import polars as pl
        from rop.embed import load_faiss_index
    except ImportError as e:
        sys.exit(f"Missing dependency: {e}\n  pip install rop-biomedical polars")

    print("Loading FAISS index …")
    index = load_faiss_index(bundle_paths["embeddings.faiss"])

    print("Loading elements parquet …")
    elements = pl.read_parquet(bundle_paths["elements.parquet"])
    print(f"  {len(elements):,} CDEs loaded")

    print("Building query texts …")
    queries = [build_query_text(t) for t in nf_terms]

    print(f"Encoding {len(queries)} NF terms with SapBERT …")
    query_vectors = batch_encode(queries)  # (N, 768) float32

    print(f"Searching FAISS index (top_n={top_n}) …")
    scores_matrix, indices_matrix = index.search(query_vectors.astype("float32"), top_n)

    # Column names available in the parquet
    available_cols = elements.columns
    keep_cols = [
        c for c in [
            "item", "description", "collection", "alternate_names",
            "source_authority", "item_type", "values", "priority",
            "rop_accession", "source_code", "source_url",
        ]
        if c in available_cols
    ]

    rows = []
    for term_idx, term in enumerate(nf_terms):
        term_hits = []
        for rank_offset in range(top_n):
            rop_idx = int(indices_matrix[term_idx, rank_offset])
            score = float(scores_matrix[term_idx, rank_offset])
            if rop_idx < 0 or score < score_cutoff:
                continue
            rop_row = elements.row(rop_idx, named=True)
            term_hits.append((rank_offset + 1, score, rop_row))

        if not term_hits:
            rows.append({
                **{k: term[k] for k in ("name", "title", "description", "source_file", "term_type", "range", "aliases")},
                "match_rank": "",
                "match_type": "no_match",
                "match_score": "",
                **{f"rop_{c}": "" for c in keep_cols},
            })
        else:
            for rank, score, rop_row in term_hits:
                rows.append({
                    **{k: term[k] for k in ("name", "title", "description", "source_file", "term_type", "range", "aliases")},
                    "match_rank": rank,
                    "match_type": "semantic",
                    "match_score": round(score, 4),
                    **{f"rop_{c}": str(rop_row.get(c) or "") for c in keep_cols},
                })

    return rows, [f"rop_{c}" for c in keep_cols]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=OUTPUT_DIR / ".bundle",
        help="Directory containing (or to download) elements.parquet and embeddings.faiss",
    )
    parser.add_argument(
        "--score-cutoff",
        type=float,
        default=0.6,
        help="Minimum cosine similarity score (0-1, default 0.6)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of top RoP matches per NF term (default 3)",
    )
    parser.add_argument(
        "--slots-only",
        action="store_true",
        help="Match only slot/attribute terms, skip enum values",
    )
    args = parser.parse_args()

    print("Extracting NF metadata dictionary terms …")
    nf_terms = extract_nf_terms()
    if args.slots_only:
        nf_terms = [t for t in nf_terms if t["term_type"] == "slot"]
    n_slots = sum(1 for t in nf_terms if t["term_type"] == "slot")
    n_enums = len(nf_terms) - n_slots
    print(f"  {len(nf_terms)} terms ({n_slots} slots, {n_enums} enum values)")

    print("Ensuring RoP bundle is available …")
    bundle_paths = ensure_bundle(args.bundle_dir)

    results, rop_cols = run_matching(nf_terms, bundle_paths, args.top_n, args.score_cutoff)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "matches.csv"
    fieldnames = [
        "name", "title", "description", "source_file", "term_type", "range", "aliases",
        "match_rank", "match_type", "match_score",
        *rop_cols,
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    matched = sum(1 for r in results if r["match_type"] != "no_match")
    n_terms_matched = sum(1 for r in results if r["match_rank"] in (1, "1"))
    print(f"\nDone. Results written to {out_path.relative_to(REPO_ROOT)}")
    print(f"  {n_terms_matched} NF terms with ≥1 match ({matched} total match rows)")
    print(f"  {len(nf_terms) - n_terms_matched} unmatched terms")


if __name__ == "__main__":
    main()
