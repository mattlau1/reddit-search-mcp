"""Build src/reddit_search/data/synonyms.json.gz from the Princeton WordNet 3.0 database files.

Dev-time only (stdlib, no nltk needed). Usage:
    python scripts/build_synonyms.py /path/to/wordnet_dir   # dir with data.noun, index.noun, ...
The NLTK 'wordnet' corpus zip contains exactly this directory.

For each single-word lemma we keep up to MAX_SYNS single-word synonyms drawn from its first MAX_SENSES
senses (WordNet orders senses by frequency; rarer senses are skipped). Synonyms are ordered by how common
the word is overall (WordNet's tagged-sense counts), so everyday words come before Latinate rarities.
"""
import gzip
import json
import re
import sys
from pathlib import Path

MAX_SENSES = 3
MAX_SYNS = 8
POS = ("noun", "verb", "adj", "adv")
WORD = re.compile(r"^[a-z]{3,}$")


def load_synsets(d: Path, pos: str) -> dict[str, list[str]]:
    out = {}
    for line in (d / f"data.{pos}").read_text(encoding="utf-8").splitlines():
        if line.startswith("  "):
            continue
        parts = line.split(" ")
        n = int(parts[3], 16)
        words = [parts[4 + 2 * i] for i in range(n)]
        out[parts[0]] = [re.sub(r"\(.*\)$", "", w).lower() for w in words]
    return out


def load_commonness(d: Path) -> dict[str, int]:
    """Total tagged-sense count per lemma across all senses (index.sense: key offset sense_no tag_cnt)."""
    c: dict[str, int] = {}
    for line in (d / "index.sense").read_text(encoding="utf-8").splitlines():
        key, _, _, cnt = line.split(" ")
        lemma = key.split("%")[0].lower()
        c[lemma] = c.get(lemma, 0) + int(cnt)
    return c


def main(d: str, out: str) -> None:
    d = Path(d)
    common = load_commonness(d)
    table: dict[str, list[str]] = {}
    for pos in POS:
        syn = load_synsets(d, pos)
        for line in (d / f"index.{pos}").read_text(encoding="utf-8").splitlines():
            if line.startswith("  "):
                continue
            p = line.split(" ")
            lemma = p[0]
            if not WORD.match(lemma):
                continue
            n_ptr = int(p[3])
            offsets = p[6 + n_ptr:][:MAX_SENSES]  # index order = frequency order
            found = table.setdefault(lemma, [])
            for off in offsets:
                for w in syn.get(off, []):
                    if w != lemma and WORD.match(w) and w not in found:
                        found.append(w)
    table = {k: sorted(v, key=lambda w: -common.get(w, 0))[:MAX_SYNS] for k, v in table.items() if v}
    with gzip.open(out, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(table, f, separators=(",", ":"), sort_keys=True)
    print(f"{len(table)} lemmas -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "src/reddit_search/data/synonyms.json.gz")
