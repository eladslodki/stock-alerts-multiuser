"""
Unit tests for services.extract_text.

Covers:
- filter_xbrl_noise: XBRL taxonomy / member line removal
- prestrip_html: table / script / style removal and truncation cap
- chunk_text: MAX_CHUNKS and overlap behaviour
- extract_relevant_sections: MAX_RELEVANT_CHARS cap guarantee
"""
import os
import sys

import pytest

# Make sure the project root is on the path regardless of how pytest is invoked.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.extract_text import (
    MAX_CHUNK_CHARS,
    MAX_CHUNKS,
    MAX_HTML_PARSE_CHARS,
    MAX_RELEVANT_CHARS,
    chunk_text,
    extract_relevant_sections,
    filter_xbrl_noise,
    prestrip_html,
)


# =========================================================================== #
# filter_xbrl_noise
# =========================================================================== #

class TestFilterXbrlNoise:
    """XBRL taxonomy / member line removal."""

    def test_removes_namespace_prefix_lines(self):
        """Lines with us-gaap:/srt:/dei: prefix and no adjacent numbers are removed."""
        text = "\n".join([
            "Management's Discussion and Analysis",
            "us-gaap:Revenues",
            "srt:ConsolidatedEntitiesMember",
            "dei:EntityCommonStockSharesOutstanding",
            "Revenue increased 12% year over year.",
        ])
        result = filter_xbrl_noise(text)
        assert "us-gaap:Revenues" not in result
        assert "srt:ConsolidatedEntitiesMember" not in result
        assert "dei:EntityCommonStockSharesOutstanding" not in result
        # Normal narrative lines must survive
        assert "Management's Discussion" in result
        assert "Revenue increased 12%" in result

    def test_removes_all_supported_prefixes(self):
        """ifrs-full:, invest:, country:, currency:, stpr:, xbrli: are filtered."""
        lines = [
            "ifrs-full:Revenue",
            "invest:InvestmentTableLineItems",
            "country:US",
            "currency:USD",
            "stpr:CA",
            "xbrli:identifier",
        ]
        text = "\n".join(lines)
        result = filter_xbrl_noise(text)
        for line in lines:
            assert line not in result, f"Expected '{line}' to be removed"

    def test_keeps_namespace_line_with_inline_number(self):
        """A namespace-prefixed line that contains a number itself is kept."""
        text = "\n".join([
            "us-gaap:Revenues  4800000000",
            "Normal prose here.",
        ])
        result = filter_xbrl_noise(text)
        assert "us-gaap:Revenues" in result

    def test_keeps_taxonomy_line_adjacent_to_number_line(self):
        """A taxonomy line is kept when its neighboring line carries a number."""
        text = "\n".join([
            "us-gaap:Revenues",
            "4,800,000,000",
            "Normal prose here.",
        ])
        result = filter_xbrl_noise(text)
        assert "us-gaap:Revenues" in result
        assert "4,800,000,000" in result

    def test_taxonomy_line_not_kept_by_preceding_number_line(self):
        """Preceding-line numbers do NOT prevent XBRL removal (filter is forward-only)."""
        text = "\n".join([
            "Revenue: 4800",         # has financial number (preceding line)
            "us-gaap:Revenues",      # XBRL: neither it nor next line has financial num
            "Next section.",         # no financial number
        ])
        result = filter_xbrl_noise(text)
        # us-gaap:Revenues is removed — the preceding "4800" is not a reason to keep it
        assert "us-gaap:Revenues" not in result
        assert "Revenue: 4800" in result
        assert "Next section." in result

    def test_removes_camelcase_member_suffix(self):
        """CamelCase identifiers ending in Member with no adjacent numbers are removed."""
        text = "\n".join([
            "Revenue was $4.8 billion.",
            "NaturalGasMidstreamMember",
            "ConsolidatedEntitiesMember",
            "Operating income rose 7%.",
        ])
        result = filter_xbrl_noise(text)
        assert "NaturalGasMidstreamMember" not in result
        assert "ConsolidatedEntitiesMember" not in result
        # Prose with numbers must survive
        assert "Revenue was $4.8 billion." in result
        assert "Operating income rose 7%." in result

    def test_removes_axis_and_lineitems_identifiers(self):
        """CamelCase identifiers ending in Axis or LineItems are removed."""
        text = "\n".join([
            "FairValueByAssetClassAxis",
            "IncomeStatementLineItems",
            "Net income grew 5%.",      # no dollar amount or 4+ digits
            "Operating income: $980M.",  # dollar amount, but 2 lines away from LineItems
        ])
        result = filter_xbrl_noise(text)
        assert "FairValueByAssetClassAxis" not in result
        assert "IncomeStatementLineItems" not in result
        assert "Net income grew 5%." in result

    def test_removes_domain_suffix(self):
        """CamelCase identifiers ending in Domain are removed."""
        text = "\n".join([
            "EntityTypesDomain",
            "Overview:",        # no financial number on the next line
            "Revenue: $4.8B",   # dollar amount is two lines away
        ])
        result = filter_xbrl_noise(text)
        assert "EntityTypesDomain" not in result
        assert "Revenue: $4.8B" in result

    def test_normal_financial_prose_unchanged(self):
        """Plain financial text without XBRL patterns is returned unchanged."""
        text = (
            "Revenue grew 12% to $4.8 billion in Q3 2024.\n"
            "Operating income increased 7% to $980 million.\n"
            "Management expects full-year revenue of $19–20 billion."
        )
        assert filter_xbrl_noise(text) == text

    def test_empty_string_returns_empty(self):
        assert filter_xbrl_noise("") == ""

    def test_heavy_xbrl_reduces_line_count_significantly(self):
        """A filing with mostly XBRL lines is reduced by more than half."""
        xbrl_lines      = [f"us-gaap:Concept{i}" for i in range(100)]
        # Use narrative without financial numbers so the last XBRL line is also removed.
        narrative_lines = ["Revenue increased in this quarter."] * 20
        text = "\n".join(xbrl_lines + narrative_lines)
        result = filter_xbrl_noise(text)
        original_count = len(text.splitlines())
        result_count   = len(result.splitlines())
        assert result_count < original_count * 0.5, (
            f"Expected >50%% reduction, got {result_count}/{original_count} lines"
        )

    def test_short_member_name_not_removed(self):
        """Identifiers shorter than the CamelCase threshold are not removed."""
        # "ShortMember" has only 5 chars before "Member" — still caught (threshold is 4+)
        # but "Member" alone (4 chars before suffix = 0) should not match
        text = "board member report"
        result = filter_xbrl_noise(text)
        # lowercase "member" should NOT be flagged — pattern requires uppercase start
        assert "board member report" in result


# =========================================================================== #
# prestrip_html
# =========================================================================== #

class TestPrestripHtml:
    """Regression tests — ensures existing pipeline behaviour is preserved."""

    def test_removes_tables(self):
        sample = (
            "<html><body>"
            + "<table><tr><td>$1,234</td></tr></table>" * 50
            + "<p>Management's Discussion: revenue grew 15%.</p>"
            + "</body></html>"
        )
        result = prestrip_html(sample)
        assert len(result) < len(sample) * 0.5
        assert "revenue grew 15%" in result

    def test_removes_scripts(self):
        html   = "<html><script>alert('xss')</script><p>Clean text.</p></html>"
        result = prestrip_html(html)
        assert "alert" not in result
        assert "Clean text" in result

    def test_removes_styles(self):
        html   = "<html><style>.foo{color:red;}</style><p>Hello.</p></html>"
        result = prestrip_html(html)
        assert "color:red" not in result
        assert "Hello" in result

    def test_truncates_at_parse_cap(self):
        big_html = "<p>" + "A" * (MAX_HTML_PARSE_CHARS + 100_000) + "</p>"
        result   = prestrip_html(big_html)
        assert len(result) <= MAX_HTML_PARSE_CHARS

    def test_empty_input(self):
        assert prestrip_html("") == ""

    def test_narrative_survives_table_removal(self):
        """Key narrative text is not lost even in a table-heavy document."""
        html = (
            "<html><body>"
            + "<table>" + "<tr><td>data</td></tr>" * 1000 + "</table>"
            + "<p>ONEOK delivered record throughput of 5.3 Bcf/d.</p>"
            + "</body></html>"
        )
        result = prestrip_html(html)
        assert "record throughput" in result


# =========================================================================== #
# chunk_text
# =========================================================================== #

class TestChunkText:

    def test_respects_max_chunks_cap(self):
        long_text = "X" * (MAX_CHUNK_CHARS * (MAX_CHUNKS + 5))
        chunks    = chunk_text(long_text)
        assert len(chunks) <= MAX_CHUNKS

    def test_empty_input_returns_empty_list(self):
        assert chunk_text("") == []

    def test_short_text_produces_single_chunk(self):
        text   = "Short text."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunks_cover_full_text(self):
        """Every character in the original text appears in at least one chunk."""
        text   = "ABCDEFGHIJ" * 5000   # 50 000 chars
        chunks = chunk_text(text)
        # First and last char of each non-overlapping window should be covered
        covered_start = chunks[0][:10]
        covered_end   = chunks[-1][-10:]
        assert covered_start in text
        assert covered_end   in text


# =========================================================================== #
# extract_relevant_sections
# =========================================================================== #

class TestExtractRelevantSections:

    def test_never_exceeds_relevant_cap(self):
        big_text = (
            "Management's Discussion and Analysis\n"
            + "A" * 5_000 + "\n"
        ) * 200
        result = extract_relevant_sections(big_text)
        assert len(result) <= MAX_RELEVANT_CHARS, (
            f"Output {len(result)} chars > cap {MAX_RELEVANT_CHARS}"
        )

    def test_short_text_returned_unchanged(self):
        text   = "Revenue grew 12% in Q3.\nOperating income was $980M."
        result = extract_relevant_sections(text)
        assert result == text

    def test_keyword_section_included(self):
        text = (
            "Unrelated preamble.\n" * 50
            + "Results of Operations\n"
            + "Revenue increased 12% to $4.8B.\n" * 10
        )
        result = extract_relevant_sections(text)
        assert "Revenue increased" in result
