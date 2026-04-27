"""Heuristic quality validator. No LLM call.

Scores generated post markdown against on-page SEO + brand voice rules.
Returns (score, issues). Engine refuses to publish if score < min_quality_score.

Keyword matching is fuzzy by design: real on-page SEO ranks on semantic relevance,
not exact-phrase repetition. We strip Italian/English leading interrogatives +
articles from the target keyword to extract a "head term," then check that the
head term's content tokens appear in the relevant field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


BANNED_PHRASES_DEFAULT = [
    "in light of", "leverage", "synergy", "synergies",
    "tailored solution", "in today's fast-paced world",
    "cutting-edge", "best-in-class", "world-class",
    # IT corporate filler
    "alla luce di", "soluzione su misura tagliata", "all'avanguardia",
]

# Words to strip from the keyword to find its head term. Italian + English.
_STOPHEAD = {
    # IT interrogatives + intent qualifiers
    "come", "cosa", "che", "quale", "quali", "quando", "dove", "perche", "perché",
    "scegliere", "trovare", "valutare", "confrontare",
    # IT articles + prepositions
    "un", "una", "uno", "il", "la", "lo", "gli", "le", "i", "del", "della",
    "dei", "delle", "al", "alla", "ai", "alle", "di", "a", "in", "per", "con",
    # EN
    "how", "what", "which", "when", "where", "why", "to", "the", "a", "an",
    "of", "for", "on", "with",
}


def _head_term_tokens(keyword: str) -> list[str]:
    """Extract content tokens from a keyword, dropping interrogatives/articles."""
    raw = re.sub(r"[^\w\s]", " ", keyword.lower())
    return [t for t in raw.split() if t and t not in _STOPHEAD]


def _kw_present(field: str, keyword: str, *, min_ratio: float = 0.75) -> bool:
    """True if the head-term tokens of `keyword` are present in `field`.

    Accepts either exact substring of the full keyword OR ≥min_ratio of the
    head tokens appearing as separate words in the field (any order).
    """
    if not field:
        return False
    field_lower = field.lower()
    if keyword.lower() in field_lower:
        return True
    tokens = _head_term_tokens(keyword)
    if not tokens:
        return False
    field_tokens = set(re.findall(r"\w+", field_lower))
    matched = sum(1 for t in tokens if t in field_tokens)
    return matched / len(tokens) >= min_ratio


@dataclass
class QualityResult:
    score: int
    issues: list[str]
    word_count: int


def _strip_frontmatter(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", md, re.DOTALL)
    if not m:
        return {}, md
    fm_raw, body = m.group(1), m.group(2)
    fm: dict = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'").strip("[").strip("]")
    return fm, body


def _strip_jsonld(body: str) -> str:
    return re.sub(r"<script type=\"application/ld\+json\">.*?</script>",
                  "", body, flags=re.DOTALL)


def validate(md: str, *, target_keyword: str,
             min_word_count: int = 1000,
             max_word_count: int = 2500,
             banned_phrases: list[str] | None = None,
             internal_link_candidates_count: int = 0) -> QualityResult:
    issues: list[str] = []
    score = 100

    fm, body = _strip_frontmatter(md)
    body_no_schema = _strip_jsonld(body)
    plain = re.sub(r"[#>*_`\[\]()!-]", " ", body_no_schema)
    plain = re.sub(r"\s+", " ", plain).strip()
    words = plain.split()
    wc = len(words)

    # 1. Frontmatter completeness
    for key in ("title", "slug", "meta_description"):
        if not fm.get(key):
            issues.append(f"frontmatter missing: {key}")
            score -= 10

    # 2. Title length (30-70)
    title = fm.get("title", "")
    if title and not (30 <= len(title) <= 70):
        issues.append(f"title length {len(title)} outside 30-70")
        score -= 5

    # 3. Meta description length (120-165)
    meta = fm.get("meta_description", "")
    if meta and not (120 <= len(meta) <= 165):
        issues.append(f"meta_description length {len(meta)} outside 120-165")
        score -= 5

    # 4. Word count with 5% tolerance under floor
    floor = int(min_word_count * 0.95)
    if wc < floor:
        issues.append(f"word count {wc} < floor {floor} (target min {min_word_count})")
        score -= 15
    elif wc < min_word_count:
        issues.append(f"word count {wc} just under {min_word_count} (within 5% tolerance)")
        score -= 3
    elif wc > max_word_count:
        issues.append(f"word count {wc} > max {max_word_count}")
        score -= 5

    # 5. Target keyword in title + meta + first 100 words (fuzzy head-term match)
    if not _kw_present(title, target_keyword):
        issues.append("target keyword head-term missing from title")
        score -= 10
    if not _kw_present(meta, target_keyword):
        issues.append("target keyword head-term missing from meta_description")
        score -= 5
    first_100 = " ".join(words[:100])
    if not _kw_present(first_100, target_keyword):
        issues.append("target keyword head-term missing from first 100 words")
        score -= 5

    # 6. Heading structure
    h2_count = len(re.findall(r"^##\s+", body_no_schema, re.MULTILINE))
    if h2_count < 3:
        issues.append(f"only {h2_count} H2 sections, need >=3")
        score -= 8
    if h2_count > 8:
        issues.append(f"{h2_count} H2 sections, may be too fragmented")
        score -= 3

    # 7. FAQ block
    faq_present = bool(re.search(r"##\s+(domande frequenti|faq)", body_no_schema, re.IGNORECASE))
    if not faq_present:
        issues.append("missing FAQ section")
        score -= 5

    # 8. No em dashes
    em_count = body_no_schema.count("—")
    if em_count:
        issues.append(f"{em_count} em-dash(es) found, must be replaced")
        score -= 5 * em_count

    # 9. Banned phrases
    blist = banned_phrases or BANNED_PHRASES_DEFAULT
    body_lower = body_no_schema.lower()
    found_banned = [p for p in blist if p in body_lower]
    if found_banned:
        issues.append(f"banned phrases: {found_banned}")
        score -= 5 * len(found_banned)

    # 10. Internal links: only required if there were candidates
    internal_links = re.findall(r"\[[^\]]+\]\((/[a-z0-9-]+/?)\)", body_no_schema)
    if not internal_links and internal_link_candidates_count > 0:
        issues.append(f"no internal links (had {internal_link_candidates_count} candidate(s))")
        score -= 3

    # 11. Keyword stuffing: head-term density > 2.5%
    head_tokens = _head_term_tokens(target_keyword)
    if wc > 0 and head_tokens:
        head_pattern = r"\b" + r"\W+".join(re.escape(t) for t in head_tokens) + r"\b"
        kw_occurrences = len(re.findall(head_pattern, body_lower))
        density = kw_occurrences / max(wc, 1)
        if density > 0.025:
            issues.append(f"head-term density {density:.2%} too high (>2.5%)")
            score -= 8

    score = max(0, min(100, score))
    return QualityResult(score=score, issues=issues, word_count=wc)
