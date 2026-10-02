from approva.engine.citations import cite_from_corpus, load_corpus, validate_citations
from approva.schemas import Citation


def test_valid_verbatim_quote_and_whitespace_case_normalization():
    corpus = load_corpus()
    citation = cite_from_corpus("SW-1.2", corpus)
    citation.quote = "  " + citation.quote.upper().replace(" ", "  ") + "  "
    valid, invalid = validate_citations([citation], corpus)
    assert valid == [citation]
    assert invalid == []


def test_paraphrase_and_unknown_clause_are_dropped():
    corpus = load_corpus()
    citations = [
        Citation(clause_id="SW-1.2", quote="A software license needs some approval."),
        Citation(clause_id="ZZ-9.9", quote="Unknown rule"),
    ]
    valid, invalid = validate_citations(citations, corpus)
    assert valid == []
    assert invalid == citations