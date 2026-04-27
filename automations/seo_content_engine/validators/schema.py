"""JSON-LD schema validator.

Parses <script type="application/ld+json"> blocks out of generated post markdown
and asserts the engine's required schemas are present + structurally valid.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


REQUIRED_TYPES = {"Article", "BreadcrumbList", "FAQPage"}


@dataclass
class SchemaResult:
    ok: bool
    issues: list[str]
    blocks: list[dict]


def extract_jsonld(md: str) -> list[dict]:
    blocks: list[dict] = []
    for m in re.finditer(
        r"<script type=\"application/ld\+json\">\s*(\{.*?\}|\[.*?\])\s*</script>",
        md, re.DOTALL,
    ):
        raw = m.group(1).strip()
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError as e:
            blocks.append({"_parse_error": str(e), "_raw": raw[:200]})
    return blocks


def validate(md: str) -> SchemaResult:
    issues: list[str] = []
    blocks = extract_jsonld(md)

    parse_errors = [b for b in blocks if "_parse_error" in b]
    if parse_errors:
        for b in parse_errors:
            issues.append(f"JSON-LD parse error: {b['_parse_error']}")

    valid = [b for b in blocks if "_parse_error" not in b]
    found_types = {b.get("@type") for b in valid if isinstance(b.get("@type"), str)}

    missing = REQUIRED_TYPES - found_types
    if missing:
        issues.append(f"missing schema types: {sorted(missing)}")

    # Per-type structural checks
    for b in valid:
        t = b.get("@type")
        if t == "Article":
            for k in ("headline", "description", "author", "datePublished", "inLanguage"):
                if k not in b:
                    issues.append(f"Article missing {k}")
        elif t == "BreadcrumbList":
            items = b.get("itemListElement", [])
            if len(items) < 2:
                issues.append("BreadcrumbList needs >=2 items")
        elif t == "FAQPage":
            entities = b.get("mainEntity", [])
            if len(entities) < 2:
                issues.append("FAQPage needs >=2 questions")
            for q in entities:
                if not isinstance(q, dict) or q.get("@type") != "Question":
                    issues.append("FAQPage entity not a Question")
                    break
                ans = q.get("acceptedAnswer") or {}
                if not ans.get("text"):
                    issues.append("FAQPage Question missing answer text")
                    break

    return SchemaResult(ok=not issues, issues=issues, blocks=valid)
