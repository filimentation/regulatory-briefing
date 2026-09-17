#!/usr/bin/env python3
"""
Daily Regulatory Briefing Generator
Fetches news from CFPB, FDIC, Federal Reserve, American Banker
Generates ELI15 summaries using Claude API
Outputs markdown file and updates RSS feed
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
from anthropic import Anthropic

# Configuration
BRIEFING_DIR = Path("briefings")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
KAGI_API_KEY = os.getenv("KAGI_API_KEY")
KAGI_API_URL = "https://kagi.com/api/v1/search"

# News sources - Kagi will search for these
NEWS_SOURCES = {
    "CFPB": {
        "query": "consumerfinance news",
        "name": "Consumer Financial Protection Bureau",
    },
    "FDIC": {
        "query": "fdic news",
        "name": "Federal Deposit Insurance Corporation",
    },
    "Federal Reserve": {
        "query": "federalreserve news",
        "name": "Federal Reserve",
    },
    "American Banker": {
        "query": "americanbanker news",
        "name": "American Banker",
    },
}


def parse_published_time(result):
    """Return a timezone-aware publication time from a Kagi result.

    Kagi may omit publication metadata or return either a naive or an
    offset-aware ISO-8601 timestamp. Normalize all cases to UTC.
    """
    published = result.get("published")
    if not published:
        return datetime.now(timezone.utc)

    try:
        published_time = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        if published_time.tzinfo is None:
            return published_time.replace(tzinfo=timezone.utc)
        return published_time.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def fetch_news_kagi(max_articles=15, hours_back=24):
    """Fetch recent news from all sources using the Kagi API."""
    all_articles = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    if not KAGI_API_KEY:
        print("ERROR: KAGI_API_KEY environment variable not set", file=sys.stderr)
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KAGI_API_KEY}",
    }

    for source_name, source_config in NEWS_SOURCES.items():
        try:
            print(f"  Searching {source_name}...", file=sys.stderr)

            payload = {
                "query": source_config["query"],
                "workflow": "news",
            }
            response = requests.post(
                KAGI_API_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            results = response.json()

            search_results = results.get("data", {}).get("results", [])
            if not search_results:
                print("    No results found", file=sys.stderr)
                continue

            print(f"    Found {len(search_results)} results", file=sys.stderr)

            for result in search_results[:5]:
                try:
                    headline = str(result.get("title") or "").strip()
                    url = str(result.get("url") or "").strip()
                    summary = str(result.get("snippet") or "").strip()
                    pub_time = parse_published_time(result)

                    if pub_time < cutoff_time:
                        print(f"    Skipping old: {headline[:50]}", file=sys.stderr)
                        continue

                    if not url or not headline:
                        print("    Skipping result without a title or URL", file=sys.stderr)
                        continue

                    article = {
                        "source": source_name,
                        "headline": headline[:200],
                        "summary": (summary or headline)[:300],
                        "url": url,
                        "published": pub_time.isoformat(),
                        "description": source_config["name"],
                    }
                    all_articles.append(article)
                    print(f"    Added: {headline[:60]}...", file=sys.stderr)

                except Exception as exc:
                    # Keep one malformed result from discarding the source.
                    print(f"    Error parsing result: {exc!r}", file=sys.stderr)

        except requests.RequestException as exc:
            print(f"  Error querying {source_name}: {exc}", file=sys.stderr)
        except (ValueError, KeyError) as exc:
            print(f"  Error reading {source_name} response: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  Unexpected error querying {source_name}: {exc!r}", file=sys.stderr)

    # Sort by publication time (newest first), then remove duplicate URLs.
    all_articles.sort(key=lambda article: article["published"], reverse=True)
    unique_articles = []
    seen_urls = set()
    for article in all_articles:
        if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    print(f"\n  Total articles found: {len(unique_articles)}", file=sys.stderr)
    return unique_articles[:max_articles]


def generate_eli15_summary(article):
    """Use Claude API to generate an ELI15 summary."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are writing a financial news briefing for banking professionals.
Explain this regulatory/banking news at an ELI15 level (explain like I'm 15).

IMPORTANT: This means:
- Use plain language, but assume the reader knows what banks do
- Explain the \"why\" not just the \"what\"
- Flag any business impact for a bank employee
- Skip jargon OR define it inline when unavoidable
- Keep to 2-3 sentences MAX for each section

Article headline: {article['headline']}
Article source: {article['source']}
Article summary: {article['summary']}

Respond in this exact JSON format (and ONLY JSON, no markdown, no backticks):
{{
  \"what_happened\": \"plain language summary of the news\",
  \"why_it_matters\": \"specific impact for banking/compliance\",
  \"business_impact\": \"one-line impact (e.g. 'Medium - Affects compliance reporting')\"
}}"""

    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        return json.loads(response_text)
    except Exception as exc:
        print(
            f"Error generating summary for '{article['headline']}': {exc}",
            file=sys.stderr,
        )
        return {
            "what_happened": article["summary"][:200],
            "why_it_matters": "See original article for details",
            "business_impact": "Review required",
        }


def create_markdown_briefing(articles, summaries):
    """Create the markdown file for today's briefing."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    md_content = f"""# Regulatory Briefing - {now.strftime('%B %d, %Y')}

**Generated:** {now.strftime('%I:%M %p %Z')}

---

"""

    for article, summary in zip(articles, summaries):
        pub_time = datetime.fromisoformat(article["published"]).strftime(
            "%b %d, %I:%M %p %Z"
        )
        md_content += f"""## {article['source']}: {article['headline']}

**Published:** {pub_time}

**What happened:** {summary.get('what_happened', 'N/A')}

**Why it matters:** {summary.get('why_it_matters', 'N/A')}

**Business impact:** {summary.get('business_impact', 'Review required')}

**Read more:** [{article['source']} article]({article['url']})

---

"""

    sources = ", ".join(sorted({article["source"] for article in articles}))
    md_content += f"""## Summary

- **Total items:** {len(articles)}
- **Sources:** {sources}
- **Generated:** {datetime.now(timezone.utc).isoformat()}
"""

    briefing_file = BRIEFING_DIR / f"{today}.md"
    briefing_file.parent.mkdir(parents=True, exist_ok=True)
    briefing_file.write_text(md_content, encoding="utf-8")

    print(f"Briefing written to {briefing_file}")
    return briefing_file


def generate_rss_feed():
    """Generate an RSS feed from all briefing markdown files."""
    briefing_files = sorted(BRIEFING_DIR.glob("*.md"), reverse=True)

    rss_root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss_root, "channel")

    ET.SubElement(channel, "title").text = "Banking Regulatory Briefing"
    ET.SubElement(channel, "link").text = (
        "https://github.com/filimentation/regulatory-briefing"
    )
    ET.SubElement(channel, "description").text = (
        "Daily ELI15 regulatory news for banking professionals"
    )
    ET.SubElement(channel, "language").text = "en-us"

    for briefing_file in briefing_files[:10]:
        content = briefing_file.read_text(encoding="utf-8")
        date_str = briefing_file.stem

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"Regulatory Briefing - {date_str}"
        ET.SubElement(item, "link").text = (
            "https://github.com/filimentation/regulatory-briefing/"
            f"blob/main/briefings/{briefing_file.name}"
        )
        ET.SubElement(item, "description").text = content[:500] + "..."
        ET.SubElement(item, "pubDate").text = datetime.strptime(
            date_str, "%Y-%m-%d"
        ).strftime("%a, %d %b %Y 06:00:00 +0000")
        ET.SubElement(item, "guid").text = f"briefing-{date_str}"

    tree = ET.ElementTree(rss_root)
    tree.write(Path("feed.xml"), encoding="utf-8", xml_declaration=True)
    print("RSS feed generated: feed.xml")


def main():
    """Main execution."""
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        return 1
    if not KAGI_API_KEY:
        print("ERROR: KAGI_API_KEY environment variable not set", file=sys.stderr)
        return 1

    print("Fetching regulatory news via Kagi...")
    articles = fetch_news_kagi(max_articles=12)
    if not articles:
        print("No articles found", file=sys.stderr)
        return 1

    print(f"Found {len(articles)} articles")
    print("Generating ELI15 summaries with Claude...")
    summaries = []
    for index, article in enumerate(articles, 1):
        print(
            f"  [{index}/{len(articles)}] "
            f"{article['source']}: {article['headline'][:50]}..."
        )
        summaries.append(generate_eli15_summary(article))

    print("Summaries generated")
    create_markdown_briefing(articles, summaries)
    generate_rss_feed()
    print("\nBriefing complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
