# Regulatory Briefing

Daily banking regulatory news generated automatically for banking, compliance, and technology leaders.

This project monitors key financial regulatory sources, gathers recent developments from agencies like the CFPB, FDIC, OCC, and Federal Reserve, consolidates related coverage, and produces a polished briefing in Markdown and RSS feed formats.

## What this project does

The repository automates a daily regulatory briefing workflow:

- Searches recent regulatory and industry news across key sources
- Filters for banking and financial regulation topics
- Deduplicates overlapping articles
- Groups related stories into a single briefing item when multiple outlets cover the same development
- Uses Anthropic Claude to synthesize the news into executive-friendly summaries
- Saves daily output as Markdown files in `briefings/`
- Publishes an RSS feed in `feed.xml`
- Runs on a schedule via GitHub Actions

The output is intended for CISO, CIO, compliance, and executive readers who need a concise, decision-oriented view of recent developments affecting banks and financial institutions.

## Repository structure

```text
.
├── .github/
│   └── workflows/
│       └── daily-briefing.yml
├── briefings/
│   ├── .gitkeep
│   ├── 2026-09-12.md
│   └── 2026-09-17.md
├── scripts/
│   ├── generate_briefing.py
│   └── requirements.txt
├── README.md
├── feed.xml
└── .gitignore
```

## Project components

### `scripts/generate_briefing.py`

This is the core automation script. It:

- loads environment variables for API keys
- queries Kagi News for recent items across configured sources
- normalizes published dates and article metadata
- filters to recent content
- deduplicates URLs
- sends the article set to Claude for consolidation
- groups related stories into one briefing item per event
- writes a daily Markdown briefing into `briefings/YYYY-MM-DD.md`
- refreshes the RSS feed at `feed.xml`

### `scripts/requirements.txt`

Python dependencies used by the generator:

- `anthropic`
- `requests`

### GitHub Actions workflow

The workflow in `.github/workflows/daily-briefing.yml` runs the script on weekdays at a scheduled time and commits the generated output back to the repository.

## News sources monitored

The workflow is configured to search these sources:

- CFPB
- FDIC
- Federal Reserve
- American Banker
- OCC

These are defined in `NEWS_SOURCES` inside `generate_briefing.py`.

## Daily output

### Markdown briefing

Each generated briefing is saved in the `briefings/` directory using a date-based filename:

```text
briefings/2026-09-17.md
```

Each briefing includes:

- report title and generation timestamp
- one section per major regulatory development
- "What happened" summary
- "Why it matters" analysis
- "Business impact" implications
- source links
- summary counts by source and total items

### RSS feed

The project also publishes an RSS feed:

```text
feed.xml
```

This feed includes the most recent generated briefings for syndication or feed readers.

## How the pipeline works

1. The GitHub Action runs the Python script.
2. The script queries Kagi News for recent regulatory updates.
3. It collects candidate articles from configured sources.
4. It filters out stale content.
5. It removes duplicates based on URL.
6. It sends the content to Claude with instructions to group overlapping stories and produce executive summaries.
7. The script writes the final content to a Markdown file and updates `feed.xml`.
8. The workflow commits and pushes the changes back to the repository.

## Environment variables

The script expects the following secrets or environment variables:

- `ANTHROPIC_API_KEY` - used for Claude summarization
- `KAGI_API_KEY` - used to query Kagi News search API

These values are configured in the GitHub Actions workflow environment.

## Local setup

### Prerequisites

- Python 3.11+
- Access to the Kagi News API
- Access to Anthropic API

### Install dependencies

```bash
cd regulatory-briefing
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

### Run locally

```bash
export ANTHROPIC_API_KEY="your-anthropic-key"
export KAGI_API_KEY="your-kagi-key"
python scripts/generate_briefing.py
```

This will generate a new briefing in `briefings/` and refresh the RSS feed.

## Example workflow

A typical run:

```bash
python scripts/generate_briefing.py
```

The generator will:

- fetch recent market and regulatory coverage
- combine related stories
- create a daily briefing file
- output a status message to the console

## Notes on behavior

- The script is intentionally opinionated about the news sources it monitors.
- It focuses on banking and regulatory developments relevant to executive and operational decision-makers.
- Some stories may be grouped if they describe the same underlying event across multiple sources.
- If Claude processing fails, the script falls back to a simpler one-item-per-article drafting path to avoid a complete generation failure.

## Why this project exists

Banking regulators often publish fast-moving developments across fragmented media and agency channels. This project creates a lightweight, repeatable pipeline to turn that coverage into a single, consolidated briefing that is easier for leadership teams to scan and act on.

## Contributing

If you want to adapt the project:

- add or remove news sources in `NEWS_SOURCES`
- adjust the Claude prompt in `generate_briefing.py`
- modify the output format or summary style
- tune the scheduling or workflow triggers in `.github/workflows/daily-briefing.yml`

## License

This repository does not currently declare a license in the root README or repository metadata. If you plan to distribute or reuse the project broadly, add an explicit license file and document the licensing terms.

## Related files

- `scripts/generate_briefing.py` — news acquisition and briefing generation
- `briefings/` — generated daily regulatory briefings
- `feed.xml` — RSS output
- `.github/workflows/daily-briefing.yml` — automation schedule and deployment

## Summary

`regulatory-briefing` is a small but useful automation project for producing daily, executive-focused banking regulatory news briefings from multiple sources and publishing them to GitHub as structured artifacts.

It combines source monitoring, summarization, and scheduled publishing into a simple, low-maintenance pipeline suited for internal or public-facing regulatory updates.
