"""SEO content engine — main entrypoint.

Usage:
    python automations/seo_content_engine/engine.py --client polara
    python automations/seo_content_engine/engine.py --client all
    python automations/seo_content_engine/engine.py --client polara --dry-run

The "all" mode is what the daily Claude Code Routine invokes. It iterates over
active clients, checks each one's cadence, and runs the cycle only for clients
due to publish today.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import frontmatter
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from client_loader import (  # noqa: E402
    ClientConfig,
    list_active_clients,
    load_client,
)
import gen  # noqa: E402
from notifier import format_preview, send as tg_send  # noqa: E402
from validators import quality, schema  # noqa: E402
from wp_client import make_publisher  # noqa: E402
PROMPTS_DIR = ENGINE_DIR / "prompts"
PREVIEW_DIR = ENGINE_DIR.parent.parent / "workspace" / "active" / "seo-engine-previews"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | seo-engine | %(message)s",
)
log = logging.getLogger("seo-engine")


# ---------------------------------------------------------------------------
# Cadence / scheduling
# ---------------------------------------------------------------------------

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def is_due_today(cfg: ClientConfig, log_entries: list[dict]) -> bool:
    """Has the client's cadence elapsed since last published post?"""
    tz = ZoneInfo(cfg.timezone)
    today = datetime.now(tz).date()

    if today.weekday() != DAY_MAP[cfg.publish_day]:
        return False

    last = _last_published_date(log_entries)
    if last is None:
        return True

    interval = {"weekly": 7, "biweekly": 14, "monthly": 30}.get(cfg.cadence, 7)
    return (today - last) >= timedelta(days=interval - 1)


def _last_published_date(log_entries: list[dict]) -> date | None:
    pub = [e for e in log_entries if e.get("status") == "published"]
    if not pub:
        return None
    dates = []
    for e in pub:
        try:
            dates.append(date.fromisoformat(e["published_at"][:10]))
        except (KeyError, ValueError):
            continue
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# Plan + log I/O
# ---------------------------------------------------------------------------

def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    return raw.get("entries", []) if isinstance(raw, dict) else []


def _append_log(path: Path, entry: dict) -> None:
    entries = _read_log(path)
    entries.append(entry)
    _write_yaml(path, {"entries": entries})


def pick_next_slot(plan: dict) -> tuple[dict, dict] | None:
    """Returns (cluster, slot) for the next 'pending' post.

    Pillar posts within their cluster are picked first, so each cluster gets a
    foundational anchor before supporting posts go up.
    """
    clusters = plan.get("clusters", [])

    # Pillar-first sweep
    for cluster in clusters:
        for slot in cluster.get("posts", []):
            if slot.get("status") == "pending" and slot.get("pillar"):
                return cluster, slot

    # Then anything pending
    for cluster in clusters:
        for slot in cluster.get("posts", []):
            if slot.get("status") == "pending":
                return cluster, slot

    return None


def update_slot_status(plan_path: Path, cluster_id: str, slug: str,
                       *, status: str, post_id: int | None = None,
                       reason: str | None = None) -> None:
    plan = _read_yaml(plan_path)
    for cluster in plan.get("clusters", []):
        if cluster.get("cluster_id") != cluster_id:
            continue
        for slot in cluster.get("posts", []):
            if slot.get("slug") == slug:
                slot["status"] = status
                if post_id is not None:
                    slot["post_id"] = post_id
                if reason:
                    slot["last_reject_reason"] = reason
                _write_yaml(plan_path, plan)
                return
    raise KeyError(f"slot {cluster_id}/{slug} not found in plan")


# ---------------------------------------------------------------------------
# Content generation (Claude Agent SDK via CLI subprocess — uses subscription)
# ---------------------------------------------------------------------------

def _audit_constraints(audit: dict) -> list[str]:
    """Pull engine-relevant constraints out of audit YAML.

    Audit YAML schema (refreshed by /seo-audit monthly):
        critical_issues:  [str]   # things content should help fix
        priority_clusters: [str]  # cluster_ids to prioritize
        avoid: [str]              # patterns/phrases to avoid this month
        min_word_count: int       # override default
        max_word_count: int
    """
    out = []
    for c in audit.get("critical_issues", []):
        out.append(f"address-or-avoid: {c}")
    for a in audit.get("avoid", []):
        out.append(f"do not include: {a}")
    return out


def _render_prompt(*, cfg: ClientConfig, cluster: dict, slot: dict,
                   audit: dict, internal_links: list[dict]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        autoescape=select_autoescape(disabled_extensions=("j2",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("post.md.j2")

    target_wc = int(slot.get("target_word_count", 1400))
    return tpl.render(
        client_name=cfg.name,
        site_url=cfg.site_url,
        language=cfg.language,
        target_keyword=slot["keyword"],
        intent=cluster.get("intent", "informational"),
        target_word_count=target_wc,
        min_word_count=audit.get("min_word_count", max(1000, target_wc - 300)),
        max_word_count=audit.get("max_word_count", target_wc + 600),
        pillar=bool(slot.get("pillar")),
        brand_voice=cfg.voice or "(no brand voice file provided)",
        audit_constraints=_audit_constraints(audit),
        internal_link_candidates=[
            {"title": p.get("title", {}).get("rendered", "") or p.get("slug", ""),
             "slug": p.get("slug", "")}
            for p in internal_links if p.get("slug")
        ],
        semantic_neighbors=slot.get("semantic_neighbors", []) or cluster.get("semantic_neighbors", []),
        today_iso=date.today().isoformat(),
    )


def _generate(prompt: str) -> str:
    """Generate via gen.py — auto-picks subprocess (local) or OpenRouter (cloud)."""
    return gen.generate(prompt)


# ---------------------------------------------------------------------------
# Output transforms
# ---------------------------------------------------------------------------

def _md_to_html(md_body: str) -> str:
    """Lightweight md→html so WP renders cleanly even without a md plugin.

    We keep <script> blocks (JSON-LD) untouched. WP's REST accepts raw HTML in
    the `content` field. For richer rendering, install a markdown plugin and
    swap this function for a passthrough.
    """
    # Preserve script blocks
    script_blocks: list[str] = []
    def _stash(m: re.Match) -> str:
        script_blocks.append(m.group(0))
        return f"%%SCRIPT_BLOCK_{len(script_blocks)-1}%%"

    body = re.sub(r"<script[\s\S]*?</script>", _stash, md_body)

    # Headings
    body = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", body, flags=re.MULTILINE)
    body = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", body, flags=re.MULTILINE)
    body = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", body, flags=re.MULTILINE)

    # Bold + italic
    body = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", body)

    # Links
    body = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', body)

    # Lists (simple)
    lines = body.splitlines()
    out_lines: list[str] = []
    in_list = False
    for ln in lines:
        if re.match(r"^\s*[-*]\s+", ln):
            if not in_list:
                out_lines.append("<ul>")
                in_list = True
            out_lines.append("<li>" + re.sub(r"^\s*[-*]\s+", "", ln) + "</li>")
        else:
            if in_list:
                out_lines.append("</ul>")
                in_list = False
            out_lines.append(ln)
    if in_list:
        out_lines.append("</ul>")
    body = "\n".join(out_lines)

    # Paragraphs (blank-line separated chunks of plain text)
    paras = re.split(r"\n{2,}", body)
    body = "\n\n".join(
        p if p.startswith(("<h", "<ul", "<ol", "<p", "%%SCRIPT", "<script"))
        else f"<p>{p.strip()}</p>"
        for p in paras if p.strip()
    )

    # Restore script blocks
    for i, blk in enumerate(script_blocks):
        body = body.replace(f"%%SCRIPT_BLOCK_{i}%%", blk)

    return body


def _save_preview(md: str, *, client: str, slug: str) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / f"{date.today().isoformat()}-{client}-{slug}.md"
    path.write_text(md, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------

async def run_cycle(cfg: ClientConfig, *, dry_run: bool, force: bool) -> dict:
    """One publish cycle for one client. Returns a result dict."""
    log_entries = _read_log(cfg.publish_log_file)

    if not force and not is_due_today(cfg, log_entries):
        log.info("%s: not due today, skipping", cfg.name)
        return {"client": cfg.name, "skipped": "not_due"}

    plan = _read_yaml(cfg.content_plan_file)
    pick = pick_next_slot(plan)
    if pick is None:
        log.warning("%s: no pending slots in content-plan.yaml", cfg.name)
        return {"client": cfg.name, "skipped": "no_pending_slots"}

    cluster, slot = pick
    audit = _read_yaml(cfg.audit_file)

    # Internal-link candidates: live from WP unless dry-run with no creds
    internal_links: list[dict] = []
    publisher = make_publisher(
        site_url=cfg.site_url, user=cfg.api_user,
        app_password=cfg.api_password, api=cfg.api,
    )
    try:
        internal_links = await publisher.list_recent_posts(limit=20)
    except Exception as e:
        log.warning("%s: could not fetch internal links (%s); proceeding without", cfg.name, e)

    prompt = _render_prompt(cfg=cfg, cluster=cluster, slot=slot,
                            audit=audit, internal_links=internal_links)
    log.info("%s: generating post for keyword=%r", cfg.name, slot["keyword"])

    raw = _generate(prompt)

    # Strip code-fence wrapping if model added it
    fence = re.match(r"^```(?:\w+)?\s*\n(.*)\n```\s*$", raw, re.DOTALL)
    md = fence.group(1) if fence else raw

    # Validate
    qres = quality.validate(
        md,
        target_keyword=slot["keyword"],
        min_word_count=audit.get("min_word_count", 1000),
        max_word_count=audit.get("max_word_count", 2500),
        internal_link_candidates_count=len(internal_links),
    )
    sres = schema.validate(md)

    log.info("%s: quality=%d/100 (wc=%d) schema_ok=%s",
             cfg.name, qres.score, qres.word_count, sres.ok)
    if qres.issues:
        log.info("%s: quality issues: %s", cfg.name, qres.issues)
    if sres.issues:
        log.info("%s: schema issues: %s", cfg.name, sres.issues)

    if qres.score < cfg.min_quality_score or not sres.ok:
        log.error("%s: validators failed, refusing to publish", cfg.name)
        preview_path = _save_preview(md, client=cfg.name, slug=slot["slug"])
        _append_log(cfg.publish_log_file, {
            "date": datetime.now().isoformat(timespec="seconds"),
            "slug": slot["slug"],
            "keyword": slot["keyword"],
            "cluster_id": cluster["cluster_id"],
            "status": "validation_failed",
            "quality_score": qres.score,
            "schema_ok": sres.ok,
            "preview_file": str(preview_path),
            "issues": qres.issues + sres.issues,
        })
        return {"client": cfg.name, "status": "validation_failed",
                "preview_file": str(preview_path),
                "issues": qres.issues + sres.issues}

    if dry_run:
        preview_path = _save_preview(md, client=cfg.name, slug=slot["slug"])
        log.info("%s: dry-run, preview saved to %s", cfg.name, preview_path)
        return {"client": cfg.name, "status": "dry_run",
                "preview_file": str(preview_path),
                "quality_score": qres.score, "word_count": qres.word_count}

    # Real publish (as draft)
    post = frontmatter.loads(md)
    fm = post.metadata
    body_html = _md_to_html(post.content)

    excerpt = (fm.get("meta_description") or "").strip()
    title = (fm.get("title") or slot["keyword"]).strip()
    slug = (fm.get("slug") or slot["slug"]).strip()

    try:
        cat_id = await publisher.ensure_category("Blog", "blog")
        wp = await publisher.create_draft(
            title=title,
            slug=slug,
            content_html=body_html,
            excerpt=excerpt,
            categories=[cat_id],
        )
    except Exception as e:
        log.exception("%s: WP publish failed", cfg.name)
        return {"client": cfg.name, "status": "wp_error", "error": str(e)}

    post_id = wp["id"]
    preview_url = await publisher.preview_url(post_id)
    edit_url = f"{cfg.site_url}/wp-admin/post.php?post={post_id}&action=edit"

    update_slot_status(cfg.content_plan_file, cluster["cluster_id"], slot["slug"],
                       status="drafted", post_id=post_id)

    _append_log(cfg.publish_log_file, {
        "date": datetime.now().isoformat(timespec="seconds"),
        "slug": slug,
        "keyword": slot["keyword"],
        "cluster_id": cluster["cluster_id"],
        "post_id": post_id,
        "status": "drafted",
        "quality_score": qres.score,
        "word_count": qres.word_count,
    })

    chat_id = cfg.telegram_chat_id
    if not chat_id:
        try:
            chat_id = int(os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "0").strip())
        except ValueError:
            chat_id = 0

    if chat_id:
        msg = format_preview(
            client_name=cfg.name, post_id=post_id, title=title,
            keyword=slot["keyword"], word_count=qres.word_count,
            quality_score=qres.score,
            preview_url=preview_url, edit_url=edit_url,
        )
        sent = await tg_send(chat_id, msg)
        log.info("%s: draft post_id=%d created, telegram=%s (chat=%s)",
                 cfg.name, post_id, sent, chat_id)
    else:
        log.warning("%s: no telegram_chat_id; draft post_id=%d created without notification",
                    cfg.name, post_id)

    return {"client": cfg.name, "status": "drafted", "post_id": post_id,
            "preview_url": preview_url, "quality_score": qres.score}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _amain(args: argparse.Namespace) -> int:
    targets: list[str]
    if args.client == "all":
        targets = list_active_clients()
    else:
        targets = [args.client]

    if not targets:
        log.warning("no active clients to process")
        return 0

    results = []
    for name in targets:
        try:
            cfg = load_client(name)
        except Exception as e:
            log.error("could not load client %s: %s", name, e)
            results.append({"client": name, "status": "config_error", "error": str(e)})
            continue
        if not cfg.active and args.client == "all":
            continue
        try:
            results.append(await run_cycle(cfg, dry_run=args.dry_run, force=args.force))
        except Exception as e:
            log.exception("cycle failed for %s", name)
            results.append({"client": name, "status": "exception", "error": str(e)})

    print(json.dumps(results, indent=2, default=str))
    failed = sum(1 for r in results if r.get("status") in ("wp_error", "exception", "config_error"))
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help="Client name or 'all'")
    ap.add_argument("--dry-run", action="store_true",
                    help="Generate + validate, save preview, no WP write")
    ap.add_argument("--force", action="store_true",
                    help="Run cycle even if not due today (cadence override)")
    args = ap.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
