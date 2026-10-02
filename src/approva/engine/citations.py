"""Policy corpus loading and verbatim citation validation."""

from __future__ import annotations

import re
from pathlib import Path

from approva import config
from approva.schemas import Citation

CLAUSE_PATTERN = re.compile(r"^- ([A-Z]{2}-\d+\.\d+) (.+)$")


def load_corpus(directory: str | Path | None = None) -> dict[str, str]:
    """Parse clause IDs and text from all policy Markdown files."""
    folder = Path(directory) if directory else config.data_path("policies")
    corpus: dict[str, str] = {}
    for path in sorted(folder.glob("*.md")):
        with path.open(encoding="utf-8") as policy_file:
            for line in policy_file:
                match = CLAUSE_PATTERN.match(line.rstrip("\r\n"))
                if match:
                    corpus[match.group(1)] = match.group(2)
    return corpus


def _normalise(text: str) -> str:
    """Lowercase and collapse whitespace for quote matching."""
    return " ".join(text.lower().split())


def validate_citations(citations: list[Citation], corpus: dict[str, str] | None = None) -> tuple[list[Citation], list[Citation]]:
    """Split citations into verbatim-valid and invalid entries."""
    corpus = corpus or load_corpus()
    valid, invalid = [], []
    for citation in citations:
        clause = corpus.get(citation.clause_id)
        (valid if clause and _normalise(citation.quote) in _normalise(clause) else invalid).append(citation)
    return valid, invalid


def cite_from_corpus(clause_id: str, corpus: dict[str, str] | None = None) -> Citation:
    """Return a citation whose quote is the first 30 words of its clause."""
    clause = (corpus or load_corpus())[clause_id]
    return Citation(clause_id=clause_id, quote=" ".join(clause.split()[:30]))