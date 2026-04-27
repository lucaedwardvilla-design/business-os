# SEO Content Engine — Multi-Tenant

A shared engine that publishes SEO-optimized blog posts on a schedule, per-client, with audit-driven constraints and Telegram-gated review.

**Why this exists:** every active Polara AI client needs a steady stream of indexable content. One codebase, per-client config, no duplicated automation per client.

---

## How it works

```
Daily routine (09:00 IT)
     │
     ▼
engine.py --client all
     │
     ├── reads clients.yaml (registry)
     ├── for each active client:
     │     ├── load clients/{name}/seo-engine/client.yaml
     │     ├── check cadence + last publish
     │     ├── pick next pending slot from content-plan.yaml
     │     ├── pull internal-link candidates from live WP
     │     ├── render prompt (post.md.j2) + audit constraints
     │     ├── generate via `claude --print` (Sonnet 4.6, subscription)
     │     ├── validate (quality.py + schema.py heuristics)
     │     ├── POST WP REST as draft (Application Password)
     │     ├── update content-plan.yaml slot status
     │     └── send Telegram preview + /approve hint
     ▼
Approver replies in Telegram:
   /approve {client} {post_id}  → bot flips WP status=publish
   /reject  {client} {post_id} <reason>
```

Monthly audit refresh routine (separate) re-runs `/seo-audit` for each active client and writes a fresh `audit.yaml` that the engine reads on the next tick.

---

## Tech choices (and why)

| Concern         | Choice                                      | Why                                                                 |
|-----------------|---------------------------------------------|---------------------------------------------------------------------|
| Generation      | `claude --print` subprocess + Sonnet 4.6    | Subscription-billed (no Anthropic API spend per global rule)        |
| Scheduling      | Claude Code Routines (cloud)                | Zero infra cost, same auth as local Claude                          |
| Approval        | Existing Telegram bot + `/approve` command  | No new infra, reuses `telegram-bot/handlers/` pattern               |
| Storage         | YAML files on disk (per-client folders)     | Human-editable, git-trackable, no DB                                |
| Validators      | Pure Python heuristics (no LLM grading)     | Fast, deterministic, cheap. LLM grading LLM = unreliable            |
| Publisher       | WP REST + Application Password              | Standard, least-privilege editor account                            |
| Multi-CMS       | `Publisher` Protocol with WP impl only V1   | Plug-in path for future Webflow/Ghost without engine rewrite        |

---

## Onboarding a new client

For each new client, ~1 day total. **Foundation fixes are non-negotiable** — content posted to a 30/100 site won't index.

### 1. Foundation fixes (BLOCKING)

Run a fresh audit:
```
/seo-audit https://{client-site}
```

Fix every Critical and High finding before flipping `active: true`. Minimum:
- Site title + tagline (no default WP text)
- Meta descriptions on all key pages
- Working `/privacy`, `/terms`, `/cookie-policy`
- Organization + WebSite JSON-LD in theme `header.php`
- Search Console + Bing Webmaster Tools verified, sitemap submitted
- "Discourage search engines" OFF, no indexed sample posts (Hello World, default page)
- `/author/admin/` blocked or admin user renamed
- WP Application Password created for an `editor`-role user (NOT admin)

### 2. Add envs

In `business-os/.env`:
```
{CLIENT}_WP_USER=editor-bot
{CLIENT}_WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

(WP App Passwords are space-separated by default. Keep the spaces.)

### 3. Create client config

Folder: `business-os/clients/{name}/seo-engine/`

`client.yaml`:
```yaml
name: example
active: false                    # flip true after content-plan + dry-run pass
site:
  url: https://example.com
  cms: wordpress
  api: rest                      # rest (default) | xmlrpc (see "Picking api" below)
  api_user_env: EXAMPLE_WP_USER
  api_password_env: EXAMPLE_WP_APP_PASSWORD
language: it                     # it | en
cadence: weekly                  # weekly | biweekly | monthly
publish_day: mon                 # mon..sun
publish_time: "09:00"
timezone: Europe/Rome
min_quality_score: 75
voice_file: brand-voice.md
telegram_chat_id: -1001234567890
audit_file: audit.yaml
content_plan_file: content-plan.yaml
```

`brand-voice.md` — voice rules + 2-3 example paragraphs. See [polara/seo-engine/brand-voice.md](../../clients/polara/seo-engine/brand-voice.md) for a model.

`content-plan.yaml` — keyword clusters with post slots:
```yaml
clusters:
  - cluster_id: example-pillar
    pillar_keyword: example keyword
    intent: commercial            # commercial | informational | transactional | navigational
    semantic_neighbors:
      - related term 1
      - related term 2
    posts:
      - slug: example-keyword-guide
        keyword: example keyword guide
        volume: 90
        kd: 12
        target_word_count: 1400
        status: pending             # pending | drafted | approved | published | rejected
        pillar: true
        planned_for: 2026-05-04
```

Use the `seo-plan` skill + DataForSEO MCP to generate this. Aim for 4-6 pillars × 5 posts = ~25-30 slots = 6 months runway at 1/week.

`audit.yaml` — populated by `/seo-audit`, with this engine-specific structure:
```yaml
last_run: "2026-04-15"
overall_score: 82
critical_issues: []                 # list of strings the content should help address or avoid
priority_clusters: []               # cluster_ids to prioritize this month
avoid: []                           # phrases/patterns to avoid
min_word_count: 1200                # optional override
max_word_count: 2200
```

`publish_log.yaml` — append-only, the engine writes this. Start empty:
```yaml
entries: []
```

### Picking `api`: rest vs xmlrpc

Most hosts leave `client.yaml.site.api: rest` (default). It's faster and modern.

Switch to `xmlrpc` if `/wp-json/wp/v2/` POSTs return `rest_cannot_create` or `rest_forbidden` despite the user being Administrator. Confirmed cases:

- **IONOS Managed WordPress** — `IONOS Essentials` mu-plugin filters REST writes via `user_has_cap`. XML-RPC is left untouched. Polara is on this; that's why its config has `api: xmlrpc`.
- Any host with a security suite that disables REST API writes for App Password sessions (some Wordfence / iThemes configs).

How to probe: from the project root, the engine ships a one-liner. With `client.yaml` filled in but `api: rest`, run a dry-run cycle. If it errors at the WP step with `rest_cannot_create`, flip to `api: xmlrpc` and retry.

### 4. Activate

1. Dry-run: `python automations/seo_content_engine/engine.py --client {name} --dry-run --force`
2. Inspect the preview at `workspace/active/seo-engine-previews/`
3. Run a real cycle against staging (set `WP_BASE_URL` in `client.yaml.site.url` to a staging subdomain first), confirm draft + Telegram preview + `/approve` flow works
4. Flip `active: true` in `automations/seo_content_engine/clients.yaml`
5. Next daily tick picks it up

---

## Operating commands

```bash
# Manual run for one client (respects cadence)
python automations/seo_content_engine/engine.py --client polara

# Force a run regardless of cadence
python automations/seo_content_engine/engine.py --client polara --force

# Dry-run (generate + validate, save preview, no WP write)
python automations/seo_content_engine/engine.py --client polara --dry-run

# Daily tick — what the routine invokes
python automations/seo_content_engine/engine.py --client all
```

## Routines (Claude Code cloud schedules)

Set up via the `routines` skill:

| Name                          | Schedule         | Command                                                              |
|-------------------------------|------------------|----------------------------------------------------------------------|
| seo-engine-daily-tick         | `0 9 * * 1-5`    | `python automations/seo_content_engine/engine.py --client all`       |
| seo-engine-audit-refresh      | `0 8 1 * *`      | (iterates active clients, runs `/seo-audit`, writes audit.yaml)      |

The audit refresh routine is a separate Claude Code workflow because it needs to invoke a skill, not just a Python script.

## Files

```
automations/seo_content_engine/
├── engine.py                main entrypoint
├── client_loader.py         per-client config validation + env resolution
├── wp_client.py             WordPress REST publisher (Publisher Protocol)
├── notifier.py              Telegram preview + status updates
├── validators/
│   ├── quality.py           on-page SEO + voice heuristics
│   └── schema.py            JSON-LD shape validator
├── prompts/
│   └── post.md.j2           generation prompt template
├── clients.yaml             active client registry
├── requirements.txt
└── README.md                this file

clients/{name}/seo-engine/
├── client.yaml              site + cadence + thresholds + creds env names
├── brand-voice.md           voice rules + examples
├── content-plan.yaml        keyword clusters + post slots
├── audit.yaml               machine-readable, refreshed monthly
└── publish_log.yaml         append-only history
```

## Failure modes

- **`claude` CLI not on PATH** — install Claude Code, or set its full path in `_generate()`
- **WP App Password rejected (401)** — re-create the App Password under WP user profile, copy with spaces preserved
- **Quality score below threshold** — preview saved to `workspace/active/seo-engine-previews/`, log entry shows issues, no WP write. Edit the prompt or the brand-voice file and rerun with `--force`
- **No pending slots** — content-plan.yaml exhausted, regenerate clusters with `seo-plan` skill
- **Telegram preview not delivered** — engine still publishes draft; check `RELAY_URL` + `BOT_POLL_KEY` env, or fall back to direct Bot API by clearing `RELAY_URL`

## Out of scope (V2+)

- Non-WordPress publishers (Webflow / Ghost / static) — Publisher Protocol exists, V1 ships WP only
- Multi-language hreflang per client (e.g. IT + EN tracks)
- Programmatic location pages — use `seo-programmatic` skill separately
- Auto-promote/demote clusters from Search Console rank data (closed-loop ranking feedback)
