# Business OS

A starter template for running your business with AI coding assistants.

---

## What Is This?

Business OS is a folder structure that transforms AI coding tools (Claude Code, Cursor, Windsurf, etc.) from "chatbots you ask questions" into "systems that run operations."

**The mental model:** You are the manager. The AI is the executor.

---

## Supported Tools

This template works with multiple AI coding assistants:

| File | Tool |
|------|------|
| `CLAUDE.md` | Claude Code |
| `AGENTS.md` | Cursor, Windsurf, and similar |
| `GEMINI.md` | Gemini-based tools |

**Important:** These files should stay in sync. When you update one, update the others.

---

## Quick Start

### 1. Download and Open

Download this folder and open it in your preferred AI coding tool.

### 2. Add Your Business Context

Edit the files in `context/business/`:
- Add your company description
- Describe your services/offers
- Define your ideal client
- Document your brand voice

### 3. Try the Daily Brief

Run the `/morning` command to generate your daily priorities.

### 4. Process a YouTube Video

Try the included YouTube skill:
```
"Process this video: https://youtube.com/watch?v=..."
```

---

## Folder Structure

```
business-os/
│
├── CLAUDE.md             # Instructions for Claude Code
├── AGENTS.md             # Instructions for Cursor/Windsurf
├── GEMINI.md             # Instructions for Gemini tools
├── README.md             # This file
├── .env.example          # Template for environment variables
├── .env                  # Your secrets (create from .env.example)
├── .gitignore            # Keeps secrets out of git
│
├── context/              # What the AI knows about you
│   ├── business/         # Your company, offers, clients
│   └── learning/         # Research, notes, references
│
├── .claude/              # AI capabilities
│   ├── skills/           # Repeatable workflows
│   ├── commands/         # Daily triggers (/morning, etc.)
│   └── agents/           # Parallel specialists
│
└── workspace/            # All outputs
    ├── foundations/      # Tasks, wins, daily briefs
    ├── content/          # Content you create
    ├── docs/             # Project folders
    └── journal/          # Personal reflection
```

---

## Environment Variables (.env)

The `.env` file stores secrets and API keys that your skills might need.

### Setup

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your keys as needed

3. Never commit `.env` to git (it's in `.gitignore`)

### Why Use .env?

- **Security** - Keep API keys out of your code and git history
- **Portability** - Same code works with different credentials
- **Skills can use it** - Scripts can read from `.env` for API access

### Common Variables

```bash
# AI APIs (if your skills call APIs directly)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Integration APIs (for skills that connect to services)
NOTION_API_KEY=secret_...
AIRTABLE_API_KEY=pat...

# Webhooks (for automation skills)
SLACK_WEBHOOK_URL=https://hooks.slack.com/...
```

Add variables as you build skills that need them. Start empty - you may not need any.

---

## Included Skills

### YouTube Transcript Extractor

Extract and analyze YouTube video transcripts:

```bash
# Install requirement
pip install youtube-transcript-api

# Usage
"Process this video: [YouTube URL]"
```

The skill will:
1. Fetch the transcript
2. Categorize the video type
3. Extract key insights
4. Save to your learning folder

---

## Included Commands

### /morning

Generates a daily brief with:
- Your TOP 2 priorities for the day
- A quick win (10-15 min task)
- Context from your weekly goals

---

## How It Works

### Context = Memory

The `context/` folder is the AI's memory about your business. The more context you add, the less you need to explain every time.

### Skills = Capabilities

Skills are self-contained instructions for repeatable tasks. When you say "process this video," the AI follows the YouTube skill's instructions.

### Commands = Triggers

Commands are quick triggers that run specific workflows. Type `/morning` and get your daily brief.

### Workspace = Outputs

Everything the AI creates goes in `workspace/`. Keep it organized by type.

---

## Next Steps

1. **Fill in your context** - The more the AI knows, the more useful it becomes
2. **Use it daily** - Run `/morning` to start each day
3. **Create new skills** - When you find yourself repeating a process, make it a skill
4. **Watch the video series** - Learn how to build on this foundation

---

## Learn More

This template is part of the "Claude Code for Business" video series:

1. **Setup Guide** - Understanding the structure (you are here)
2. **Building Skills** - Create your own capabilities
3. **Commands & Rituals** - Daily triggers that run your day
4. **Context Deep Dive** - Why context is everything
5. **Agents & Automation** - Parallel specialists

---

## Questions?

Open an issue on the GitHub repo or leave a comment on the video.
