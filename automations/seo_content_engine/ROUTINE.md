# SEO Engine — Cloud Routine Setup

This is the always-on, PC-off-tolerant deployment. It runs in **Anthropic's cloud** via Claude Code Routines (`claude.ai/code/scheduled`), uses your Claude Code subscription (no API), and pushes state changes back to the `business-os` GitHub repo.

## How it works

```
Mon 09:00 IT (cron)
   │
   ▼
Claude Code Routine fires
   │
   ├── git pull origin main                            (latest configs + state)
   ├── for each active client in clients.yaml:
   │     ├── load client.yaml + brand-voice.md +
   │     │   content-plan.yaml + audit.yaml
   │     ├── pick next pending slot (pillar-first)
   │     ├── generate post markdown (Claude itself,
   │     │   no API, follows post.md.j2 template)
   │     ├── save to /tmp/post.md
   │     └── python publish_post.py --client X --md-file /tmp/post.md
   │           ├── validators (quality + schema)
   │           ├── WP draft via XML-RPC
   │           ├── update content-plan.yaml status
   │           ├── append publish_log.yaml
   │           └── Telegram preview to your existing bot
   ├── git commit -am "seo-engine: state update {date}"
   └── git push origin main
```

## Environment the routine needs

Set these in the routine's environment (claude.ai/code/scheduled → secrets):

| Variable                 | Source                               | Used for                        |
|--------------------------|--------------------------------------|---------------------------------|
| `POLARA_WP_USER`         | from `business-os/.env`              | XML-RPC auth                    |
| `POLARA_WP_APP_PASSWORD` | from `business-os/.env`              | XML-RPC auth                    |
| `TELEGRAM_BOT_TOKEN`     | from `business-os/.env`              | Direct Bot API for previews     |
| `TELEGRAM_ALLOWED_CHAT_ID` | from `business-os/.env`            | Where previews land             |
| `RELAY_URL` (optional)   | from `business-os/.env`              | If set, previews go via relay   |
| `BOT_POLL_KEY` (optional) | from `business-os/.env`             | Auth for relay                  |

These are sensitive; never paste them in chat. Use the routine console.

## Routine prompt

Copy this verbatim into the routine prompt field on `claude.ai/code/scheduled`:

```
You are the Polara SEO Content Engine, running as a scheduled routine.

Goal: publish one SEO-optimized blog post per active client per cadence.

Steps (run in order, stop on first error and report):

1. Read business-os/automations/seo_content_engine/clients.yaml.
   For each client where active=true, do steps 2-9.

2. Read business-os/clients/{client}/seo-engine/client.yaml.
   Verify today is the publish_day for this client and the cadence has elapsed
   since the last "published" entry in publish_log.yaml. If not, skip.

3. Read content-plan.yaml. Pick the next slot where status=="pending",
   pillar-first within each cluster.

4. Read brand-voice.md and audit.yaml for this client.

5. Read business-os/automations/seo_content_engine/prompts/post.md.j2 to
   understand the output format. You will produce a Markdown document with
   YAML frontmatter, body, and 3 JSON-LD blocks (Article + BreadcrumbList +
   FAQPage), exactly as the template specifies.

6. Generate the blog post for the chosen slot. Strict requirements:
   - Language: client.yaml.language (it for Polara)
   - Match brand-voice.md exactly: no em dashes, no corporate filler,
     direct register, "tu" not "Lei", concrete examples with real numbers
   - Word count: between audit.min_word_count and audit.max_word_count
     (default 1200-2200 if not specified)
   - Honor every audit.critical_issues + audit.avoid constraint
   - Include the slot's target keyword's head term in title, meta_description,
     first 100 words, and at least one H2
   - 4-6 H2 sections + an FAQ section near the end with 3-4 H3 questions
   - Hard-baked schema: Article + BreadcrumbList + FAQPage JSON-LD blocks

7. Save the generated markdown to /tmp/post.md.

8. Run: python business-os/automations/seo_content_engine/publish_post.py \
        --client {client} --md-file /tmp/post.md
   Capture the JSON output. If status is not "drafted", log the issues and
   stop processing this client (move to next).

9. After all clients processed, run from the repo root:
   git add business-os/clients/*/seo-engine/content-plan.yaml \
           business-os/clients/*/seo-engine/publish_log.yaml
   git commit -m "seo-engine: $(date +%Y-%m-%d) cycle"
   git push origin main

Failure handling: if any step fails, report the error in the run summary
and let the next scheduled run retry. Do NOT bypass validators. Do NOT
publish posts that fail quality_score < client.min_quality_score.

Telegram approval flow:
- This routine creates posts as DRAFTS only (status=draft on WP).
- Luca approves by replying "/approve {client} {post_id}" in the existing
  Telegram bot, which flips status to publish.
- Do NOT auto-publish.
```

## Schedule

Cron expression: `0 9 * * 1-5` (weekdays 09:00 Europe/Rome).

Polara's `client.yaml` has `cadence: weekly` and `publish_day: mon`, so the
routine fires every weekday but only Polara's Monday tick generates a post.
Other days are no-ops. Future clients with biweekly/monthly cadence get
picked up the same way.

## Repo access

The routine clones the `business-os` repo (https://github.com/riccardovandra/business-os) at the start of each run and pushes state-changing commits back at the end. Set up GitHub access in the routine console (App or PAT with repo write).

## Local dev still works

Your local `python engine.py --client polara --dry-run --force` flow is unchanged. It uses subprocess to the local `claude` CLI. The routine is the production path; local is for iteration.

## Monitoring

Each cycle's output is logged in:
- `business-os/clients/{client}/seo-engine/publish_log.yaml` (per-client, git-tracked)
- The routine run console on `claude.ai/code/scheduled`
- Telegram preview message (your phone)

If the routine fails, you'll see the error in `claude.ai/code/scheduled` history. The next day's scheduled run will retry — by design, single failures don't break the pipeline.
