"""Ship a pre-generated post.

Used by the Claude Code Routine (cloud, scheduled). The routine generates the
markdown itself (Claude is the generator in routine context), then calls this
script to validate, publish, update state, and notify.

Local dev can also use this to test the publish path against a hand-edited
preview file.

Usage:
    python publish_post.py --client polara --md-file /tmp/post.md
    python publish_post.py --client polara --md-file /tmp/post.md --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import frontmatter

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import engine  # noqa: E402  - reuses engine helpers (yaml, slot lookup, html, log)
from client_loader import load_client  # noqa: E402
from notifier import format_preview, send as tg_send  # noqa: E402
from validators import quality, schema  # noqa: E402
from wp_client import make_publisher  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | seo-engine.publish | %(message)s",
)
log = logging.getLogger("seo-engine.publish")


def _resolve_telegram_chat(cfg) -> int:
    """If client.yaml.telegram_chat_id is 0/missing, fall back to env."""
    if cfg.telegram_chat_id and cfg.telegram_chat_id != 0:
        return cfg.telegram_chat_id
    fallback = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "0").strip()
    try:
        return int(fallback)
    except ValueError:
        return 0


async def ship(*, client_name: str, md_path: Path, dry_run: bool) -> dict:
    cfg = load_client(client_name)
    md = md_path.read_text(encoding="utf-8")

    # Find which slot this post claims (by frontmatter slug)
    fm_post = frontmatter.loads(md)
    slug = (fm_post.metadata.get("slug") or "").strip()
    target_keyword = (fm_post.metadata.get("target_keyword") or "").strip()
    if not slug or not target_keyword:
        return {"client": client_name, "status": "bad_input",
                "error": "frontmatter missing slug or target_keyword"}

    plan = engine._read_yaml(cfg.content_plan_file)
    cluster = slot = None
    for c in plan.get("clusters", []):
        for s in c.get("posts", []):
            if s.get("slug") == slug:
                cluster, slot = c, s
                break
        if slot:
            break
    if not slot:
        return {"client": client_name, "status": "bad_input",
                "error": f"slug {slug!r} not found in content-plan.yaml"}

    audit = engine._read_yaml(cfg.audit_file)

    # Pull internal-link candidates so the validator's cold-start logic stays accurate
    publisher = make_publisher(
        site_url=cfg.site_url, user=cfg.api_user,
        app_password=cfg.api_password, api=cfg.api,
    )
    try:
        internal_links = await publisher.list_recent_posts(limit=20)
    except Exception as e:
        log.warning("could not fetch internal links (%s); proceeding without", e)
        internal_links = []

    # Validate
    qres = quality.validate(
        md,
        target_keyword=target_keyword,
        min_word_count=audit.get("min_word_count", 1000),
        max_word_count=audit.get("max_word_count", 2500),
        internal_link_candidates_count=len(internal_links),
    )
    sres = schema.validate(md)
    log.info("quality=%d/100 (wc=%d) schema_ok=%s", qres.score, qres.word_count, sres.ok)
    if qres.issues:
        log.info("quality issues: %s", qres.issues)
    if sres.issues:
        log.info("schema issues: %s", sres.issues)

    if qres.score < cfg.min_quality_score or not sres.ok:
        log.error("validation failed; refusing to publish")
        engine._append_log(cfg.publish_log_file, {
            "date": datetime.now().isoformat(timespec="seconds"),
            "slug": slug,
            "keyword": target_keyword,
            "cluster_id": cluster["cluster_id"],
            "status": "validation_failed",
            "quality_score": qres.score,
            "schema_ok": sres.ok,
            "issues": qres.issues + sres.issues,
        })
        return {"client": client_name, "status": "validation_failed",
                "quality_score": qres.score, "issues": qres.issues + sres.issues}

    if dry_run:
        log.info("dry-run, not posting to WP")
        return {"client": client_name, "status": "dry_run",
                "quality_score": qres.score, "word_count": qres.word_count}

    # Publish as draft
    body_html = engine._md_to_html(fm_post.content)
    title = (fm_post.metadata.get("title") or target_keyword).strip()

    try:
        cat_id = await publisher.ensure_category("Blog", "blog")
        wp = await publisher.create_draft(
            title=title, slug=slug, content_html=body_html,
            excerpt=(fm_post.metadata.get("meta_description") or "").strip(),
            categories=[cat_id],
        )
    except Exception as e:
        log.exception("WP publish failed")
        return {"client": client_name, "status": "wp_error", "error": str(e)}

    post_id = wp["id"]
    preview_url = await publisher.preview_url(post_id)
    edit_url = f"{cfg.site_url}/wp-admin/post.php?post={post_id}&action=edit"

    # Update content-plan slot status
    engine.update_slot_status(
        cfg.content_plan_file, cluster["cluster_id"], slug,
        status="drafted", post_id=post_id,
    )

    engine._append_log(cfg.publish_log_file, {
        "date": datetime.now().isoformat(timespec="seconds"),
        "slug": slug,
        "keyword": target_keyword,
        "cluster_id": cluster["cluster_id"],
        "post_id": post_id,
        "status": "drafted",
        "quality_score": qres.score,
        "word_count": qres.word_count,
    })

    # Telegram preview
    chat_id = _resolve_telegram_chat(cfg)
    if chat_id:
        msg = format_preview(
            client_name=cfg.name, post_id=post_id, title=title,
            keyword=target_keyword, word_count=qres.word_count,
            quality_score=qres.score,
            preview_url=preview_url, edit_url=edit_url,
        )
        sent = await tg_send(chat_id, msg)
        log.info("telegram sent=%s chat_id=%s", sent, chat_id)
    else:
        log.warning("no telegram_chat_id resolved; skipping notification")

    return {"client": client_name, "status": "drafted", "post_id": post_id,
            "preview_url": preview_url, "edit_url": edit_url,
            "quality_score": qres.score, "word_count": qres.word_count}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--md-file", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.md_file.exists():
        sys.exit(f"missing markdown file: {args.md_file}")

    result = asyncio.run(ship(
        client_name=args.client, md_path=args.md_file, dry_run=args.dry_run,
    ))
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result.get("status") in ("drafted", "dry_run") else 1)


if __name__ == "__main__":
    main()
