#!/usr/bin/env python3
"""Generate the daily banking regulatory briefing."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
from anthropic import Anthropic


BRIEFING_DIR = Path("briefings")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
KAGI_API_KEY = os.getenv("KAGI_API_KEY")
KAGI_API_URL = "https://kagi.com/api/v1/search"

NEWS_SOURCES = {
    "CFPB": {
        "query": "Consumer Financial Protection Bureau news",
        "name": "Consumer Financial Protection Bureau",
    },
    "FDIC": {
        "query": "fdic news",
        "name": "Federal Deposit Insurance Corporation",
    },
    "Federal Reserve": {
        "query": "Federal Reserve news",
        "name": "Federal Reserve",
    },
    "The Financial Brand": {
        "query": "The Financial Brand news",
        "name": "The Financial Brand",
    },
    "Disruption Banking": {
        "query": "Disruption Banking news",
        "name": "Disruption Banking",
    },
    "Independent Banker": {
        "query": "Independent Banker news",
        "name": "Independent Banker",
    },
    "Kansas City Fed": {
        "query": "Kansas City Fed news",
        "name": "Kansas City Fed",
    },
    "American Banker": {
        "query": "americanbanker news",
        "name": "American Banker",
    },
    "OCC": {
        "query": "Office of the Comptroller of the Currency news",
        "name": "Office of the Comptroller of the Currency",
    },
    "Nebraska Bankers Association": {
        "query": "Nebraska Bankers Association news",
        "name": "Nebraska Bankers Association",
    },
}

ROLE_CONFIGS = {
    "CEO-PRESIDENT": {
        "label": "CEO / President",
        "file_suffix": "CEO-PRESIDENT",
        "persona": "Chief Executive Officer (CEO) and President",
        "instructions": (
            "Focus on strategic business implications, competitive positioning, "
            "regulatory developments, reputation and brand risk, customer and "
            "market impacts, economic trends, growth opportunities, board-level "
            "concerns, enterprise risk, and long-term organizational impact. "
            "Emphasize why leadership should care and whether the issue requires "
            "monitoring, discussion, or action. Do not repeat the article summary. "
            "Keep the response to 1-3 concise sentences. Assume the audience is "
            "focused on strategic decision-making rather than operational details."
        ),
        "fallback": (
            "This development merits executive attention due to strategic, "
            "reputational, or regulatory implications that could affect the bank's "
            "positioning, operating model, or long-term priorities."
        ),
    },
    "CONTROLLER": {
        "label": "Controller Management Team",
        "file_suffix": "CONTROLLER",
        "persona": "Controller Management Team",
        "instructions": (
            "Focus on Call Report implications, accounting and financial reporting "
            "impacts, regulatory reporting requirements, audit and examination "
            "readiness, financial controls and governance, policy and procedure "
            "changes, capital and balance sheet reporting, operational impacts to "
            "accounting and finance functions, and emerging regulatory requirements. "
            "Highlight anything that may require additional analysis, monitoring, "
            "documentation, reporting, or process changes. Do not repeat the article "
            "summary. Keep the response to 1-3 concise sentences. Assume the audience "
            "consists of banking accounting and finance leaders."
        ),
        "fallback": (
            "This issue likely warrants finance and control team review for any reporting, "
            "documentation, or policy implications that could affect readiness, "
            "governance, or examination posture."
        ),
    },
    "CFO": {
        "label": "Chief Financial Officer",
        "file_suffix": "CFO",
        "persona": "Chief Financial Officer (CFO)",
        "instructions": (
            "Focus on earnings and profitability, interest rate risk, liquidity and "
            "funding, capital planning and capital ratios, regulatory changes, strategic "
            "planning, mergers and acquisitions, financial performance trends, and "
            "material operational or compliance risks that could impact financial results. "
            "Highlight any potential financial, regulatory, or strategic implications the "
            "CFO should monitor. Do not repeat the article summary. Keep the response to "
            "1-3 concise sentences. Assume the reader has extensive banking and "
            "financial expertise."
        ),
        "fallback": (
            "This development deserves financial review because it may affect earnings, "
            "capital planning, liquidity, or strategic decisions that influence the bank's "
            "financial outlook."
        ),
    },
    "CIO-CISO": {
        "label": "Chief Information Officer / Chief Information Security Officer",
        "file_suffix": "CIO-CISO",
        "persona": "Chief Information Officer (CIO) and Chief Information Security Officer (CISO)",
        "instructions": (
            "Focus on cybersecurity threats and trends, technology risk, third-party and "
            "vendor risk, regulatory expectations related to information security, data "
            "protection and privacy requirements, operational resilience and business "
            "continuity, infrastructure and architecture concerns, emerging technologies, "
            "AI, cloud, and digital banking, fraud prevention, and potential impacts to "
            "security operations. Identify any risks, controls, monitoring activities, or "
            "technology considerations that should be evaluated. Do not repeat the article "
            "summary. Keep the response to 1-3 concise sentences. Assume the audience "
            "consists of senior technology and cybersecurity leaders within a regulated "
            "financial institution."
        ),
        "fallback": (
            "This issue should be reviewed for cybersecurity, technology, vendor, or "
            "operational resilience implications that could require additional controls, "
            "monitoring, or governance attention."
        ),
    },
}


def parse_published_time(result):
    """Read any publication field Kagi provides, normalizing it to UTC."""
    published = (
        result.get("published")
        or result.get("published_at")
        or result.get("date")
        or result.get("datetime")
    )

    if not published:
        return datetime.now(timezone.utc)

    try:
        value = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def extract_results(payload):
    """Support the Kagi API response shapes used by the API playground."""
    data = payload.get("data", payload) if isinstance(payload, dict) else payload

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("results", "news", "items"):
            if isinstance(data.get(key), list):
                return data[key]

    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]

    return []


def fetch_news_kagi(max_articles=40, hours_back=24):
    """Fetch recent news from all configured sources using the Kagi API."""
    all_articles = []
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    if not KAGI_API_KEY:
        print("ERROR: KAGI_API_KEY environment variable not set", file=sys.stderr)
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KAGI_API_KEY}",
    }

    results_per_source = max(1, max_articles // len(NEWS_SOURCES))

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

            response_json = response.json()
            search_results = extract_results(response_json)

            if not search_results:
                response_keys = (
                    list(response_json)
                    if isinstance(response_json, dict)
                    else type(response_json).__name__
                )
                print(
                    f"    No results found "
                    f"(HTTP {response.status_code}; response keys: {response_keys})",
                    file=sys.stderr,
                )
                continue

            print(f"    Found {len(search_results)} results", file=sys.stderr)

            for result in search_results[:results_per_source]:
                try:
                    headline = str(
                        result.get("title") or result.get("name") or ""
                    ).strip()
                    url = str(
                        result.get("url") or result.get("link") or ""
                    ).strip()
                    summary = str(
                        result.get("snippet")
                        or result.get("description")
                        or ""
                    ).strip()
                    pub_time = parse_published_time(result)

                    if pub_time < cutoff_time:
                        print(
                            f"    Skipping old: {headline[:50]}",
                            file=sys.stderr,
                        )
                        continue

                    if not url or not headline:
                        print(
                            "    Skipping result without a title or URL",
                            file=sys.stderr,
                        )
                        continue

                    all_articles.append(
                        {
                            "source": source_name,
                            "headline": headline[:200],
                            "summary": (summary or headline)[:1000],
                            "url": url,
                            "published": pub_time.isoformat(),
                            "description": source_config["name"],
                        }
                    )

                    print(
                        f"    Added: {headline[:60]}...",
                        file=sys.stderr,
                    )

                except Exception as exc:
                    print(
                        f"    Error parsing result: {exc!r}",
                        file=sys.stderr,
                    )

        except requests.RequestException as exc:
            print(
                f"  Error querying {source_name}: {exc}",
                file=sys.stderr,
            )
        except (ValueError, KeyError) as exc:
            print(
                f"  Error reading {source_name} response: {exc}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"  Unexpected error querying {source_name}: {exc!r}",
                file=sys.stderr,
            )

    all_articles.sort(key=lambda article: article["published"], reverse=True)

    unique_articles = []
    seen_urls = set()

    for article in all_articles:
        if article["url"] not in seen_urls:
            seen_urls.add(article["url"])
            unique_articles.append(article)

    print(
        f"\n  Total unique articles found: {len(unique_articles)}",
        file=sys.stderr,
    )

    return unique_articles[:max_articles]


def fallback_briefing_items(articles):
    """Create safe briefing items if the Claude request fails."""
    items = []

    for article in articles:
        items.append(
            {
                "article_indices": [articles.index(article)],
                "headline": article["headline"],
                "what_happened": article["summary"][:1000],
                "why_it_matters": "Review the original article for regulatory and operational implications.",
                "business_impact": "Review required.",
            }
        )

    return items


def generate_briefing_items(articles):
    """
    Consolidate overlapping articles and write their briefing summaries in one
    Claude request.
    """
    if not articles:
        return [], True

    article_list = "\n\n".join(
        (
            f"ARTICLE INDEX: {index}\n"
            f"HEADLINE: {article['headline']}\n"
            f"SOURCE: {article['source']}\n"
            f"PUBLISHED: {article['published']}\n"
            f"SUMMARY: {article['summary']}\n"
            f"URL: {article['url']}"
        )
        for index, article in enumerate(articles)
    )

    prompt = f"""You are producing a daily banking regulatory news briefing for CISO- and CIO-level executives at a bank.

Review the articles below and group together articles that cover the same underlying event, announcement, rule, enforcement action, speech, or regulatory development.

Only combine articles when they clearly describe the same underlying story. Do not combine articles merely because they concern the same regulator, subject, or general theme.

For each group, produce one briefing item. Every article index must appear exactly once in exactly one group.

Writing requirements:
- Assume the reader is familiar with banking, IT, cybersecurity, compliance, third-party risk, exam cycles, and safety-and-soundness.
- Do not define standard industry jargon.
- Write in a polished, board-ready memo style that is concise, specific, and decision-relevant.
- Focus on what changed, why it matters now, and what operational or strategic decisions the issue may require.
- Highlight concrete implications for compliance, security, technology planning, budget allocation, examiner expectations, vendor oversight, board reporting, or incident response.
- Avoid generic commentary and avoid language that reads like marketing or a news brief.
- Keep the tone executive and analytical, with enough depth to inform action without drifting into narrative detail.
- Do not use the terms "ELI5" or "ELI15."

Return ONLY valid JSON using exactly this structure:

{{
  "items": [
    {{
      "article_indices": [0, 3],
      "headline": "Short, precise combined headline",
      "what_happened": "Two to four sentences describing what changed, which agency or institution acted, and the relevant scope or timing.",
      "why_it_matters": "Four to six sentences explaining the operational, compliance, security, technology, board, or regulatory significance and why the issue should be elevated now.",
      "business_impact": "One to two sentences describing the concrete business, operational, or strategic impact."
    }}
  ]
}}

Articles:

{article_list}
"""

    claude_success = True

    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        text = (
            message.content[0].text
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )

        response = json.loads(text)
        generated_items = response.get("items", [])

        if not isinstance(generated_items, list) or not generated_items:
            raise ValueError("Claude returned no briefing items")

        valid_items = []
        used_indices = set()

        for item in generated_items:
            if not isinstance(item, dict):
                continue

            raw_indices = item.get("article_indices", [])
            if not isinstance(raw_indices, list):
                continue

            indices = []
            for index in raw_indices:
                if isinstance(index, int) and 0 <= index < len(articles):
                    if index not in used_indices:
                        indices.append(index)

            if not indices:
                continue

            headline = str(item.get("headline") or "").strip()
            what_happened = str(item.get("what_happened") or "").strip()
            why_it_matters = str(item.get("why_it_matters") or "").strip()
            business_impact = str(item.get("business_impact") or "").strip()

            if not headline:
                headline = articles[indices[0]]["headline"]
            if not what_happened:
                what_happened = articles[indices[0]]["summary"]
            if not why_it_matters:
                why_it_matters = "Review the original article for specific implications."
            if not business_impact:
                business_impact = "Review required."

            valid_items.append(
                {
                    "article_indices": indices,
                    "headline": headline,
                    "what_happened": what_happened,
                    "why_it_matters": why_it_matters,
                    "business_impact": business_impact,
                }
            )
            used_indices.update(indices)

        for index, article in enumerate(articles):
            if index not in used_indices:
                valid_items.append(
                    {
                        "article_indices": [index],
                        "headline": article["headline"],
                        "what_happened": article["summary"],
                        "why_it_matters": "Review the original article for specific implications.",
                        "business_impact": "Review required.",
                    }
                )

        return valid_items, claude_success

    except Exception as exc:
        print(
            f"Error generating consolidated briefing with Claude: {exc}",
            file=sys.stderr,
        )
        print(
            "Falling back to one unsummarized item per article.",
            file=sys.stderr,
        )
        claude_success = False
        return fallback_briefing_items(articles), claude_success


def build_consolidated_articles(articles, briefing_items):
    """Attach source metadata and links to Claude's consolidated items."""
    consolidated_articles = []
    summaries = []

    for item in briefing_items:
        indices = item["article_indices"]
        source_articles = [articles[index] for index in indices]

        consolidated_articles.append(
            {
                "source": ", ".join(
                    sorted({article["source"] for article in source_articles})
                ),
                "headline": item["headline"],
                "summary": item["what_happened"],
                "url": source_articles[0]["url"],
                "published": max(article["published"] for article in source_articles),
                "related_urls": [article["url"] for article in source_articles],
            }
        )

        summaries.append(
            {
                "what_happened": item["what_happened"],
                "why_it_matters": item["why_it_matters"],
                "business_impact": item["business_impact"],
            }
        )

    return consolidated_articles, summaries


def create_markdown_briefing(articles, summaries, kagi_success, claude_success):
    """Write the consolidated briefing as Markdown."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    data_sources = "Limited" if not kagi_success else "Kagi"
    analysis_engine = "Limited" if not claude_success else "Anthropic Claude"

    content = (
        f"# Regulatory Briefing - {now.strftime('%B %d, %Y')}\n\n"
        f"**Generated:** {now.strftime('%I:%M %p %Z')}\n"
        f"**Data Sources:** {data_sources}\n"
        f"**Analysis Engine:** {analysis_engine}\n\n"
        "---\n\n"
    )

    for article, summary in zip(articles, summaries):
        published = datetime.fromisoformat(article["published"]).strftime(
            "%b %d, %I:%M %p %Z"
        )

        content += (
            f"## {article['source']}: {article['headline']}\n\n"
            f"**Published:** {published}\n\n"
            f"**What happened:** {summary.get('what_happened', 'N/A')}\n\n"
            f"**Why it matters:** {summary.get('why_it_matters', 'N/A')}\n\n"
            f"**Business impact:** {summary.get('business_impact', 'N/A')}\n\n"
        )

        related_urls = article.get("related_urls") or [article["url"]]
        content += "**Sources:**\n\n"
        for url in related_urls:
            content += f"- {url}\n"
        content += "\n---\n\n"

    sources = ", ".join(
        sorted(
            {
                source.strip()
                for article in articles
                for source in article["source"].split(",")
            }
        )
    )

    content += (
        "## Summary\n\n"
        f"- **Total items:** {len(articles)}\n"
        f"- **Sources:** {sources}\n"
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}\n"
    )

    briefing_file = BRIEFING_DIR / f"{today}.md"
    briefing_file.parent.mkdir(parents=True, exist_ok=True)
    briefing_file.write_text(content, encoding="utf-8")

    print(f"Briefing written to {briefing_file}")
    return briefing_file


def build_role_prompt(role_key, role_config, articles):
    """Build a role-specific prompt for a set of consolidated articles."""
    article_list = "\n\n".join(
        (
            f"ARTICLE INDEX: {index}\n"
            f"HEADLINE: {article['headline']}\n"
            f"SOURCE: {article['source']}\n"
            f"PUBLISHED: {article['published']}\n"
            f"SUMMARY: {article['summary']}\n"
            f"URL: {article['url']}"
        )
        for index, article in enumerate(articles)
    )

    prompt = f"""You are writing for the {role_config['persona']} of Union Bank & Trust Company, a community financial institution headquartered in Lincoln, Nebraska.

For each news article, write two role-specific sections from the {role_config['label']} perspective:
1) a "Why it Matters" section
2) a "Business Impact" section

Follow these requirements:
{role_config['instructions']}

Return ONLY valid JSON with this structure:
{{
  "items": [
    {{
      "article_index": 0,
      "why_it_matters": "1-3 concise sentences that explain why this matters to this role.",
      "business_impact": "1-2 concise sentences describing the concrete business, operational, or strategic impact to this role."
    }}
  ]
}}

Use article_index values that correspond to the ARTICLE INDEX values below.
Do not invent new article_index values.
Do not repeat the article summary. Keep each response concise and decision-focused.

Articles:

{article_list}
"""
    return prompt


def generate_role_briefings(articles, role_configs, claude_success):
    """Return per-role why-it-matters and business-impact text keyed by article index."""
    outputs = {}

    for role_key, role_config in role_configs.items():
        by_index = {}

        if claude_success:
            try:
                prompt = build_role_prompt(role_key, role_config, articles)
                client = Anthropic(api_key=ANTHROPIC_API_KEY)
                message = client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=8000,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = (
                    message.content[0].text
                    .replace("```json", "")
                    .replace("```", "")
                    .strip()
                )
                response = json.loads(text)
                generated_items = response.get("items", [])

                if isinstance(generated_items, list):
                    for item in generated_items:
                        if not isinstance(item, dict):
                            continue
                        try:
                            index = int(item.get("article_index"))
                        except (TypeError, ValueError):
                            continue
                        if 0 <= index < len(articles):
                            why = str(item.get("why_it_matters") or "").strip()
                            impact = str(item.get("business_impact") or "").strip()
                            if why or impact:
                                by_index[index] = {
                                    "why_it_matters": why or role_config["fallback"],
                                    "business_impact": impact or "This issue requires role-specific review and follow-up.",
                                }

            except Exception as exc:
                print(
                    f"Error generating {role_key} role briefing: {exc}",
                    file=sys.stderr,
                )
                claude_success = False

        if not claude_success:
            for index, article in enumerate(articles):
                by_index[index] = {
                    "why_it_matters": role_config["fallback"].format(
                        article_title=article["headline"],
                        source=article["source"],
                    ),
                    "business_impact": (
                        "This issue should be reviewed in the context of this role's "
                        "operating priorities, risk appetite, and governance responsibilities."
                    ),
                }

        outputs[role_key] = by_index

    return outputs


def create_role_markdown_briefing(role_key, role_config, articles, summaries, role_why, kagi_success, claude_success):
    """Write a role-specific briefing file with all three sections preserved."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    data_sources = "Limited" if not kagi_success else "Kagi"
    analysis_engine = "Limited" if not claude_success else "Anthropic Claude"

    content = (
        f"# Regulatory Briefing - {now.strftime('%B %d, %Y')} | {role_config['label']}\n\n"
        f"**Generated:** {now.strftime('%I:%M %p %Z')}\n"
        f"**Data Sources:** {data_sources}\n"
        f"**Analysis Engine:** {analysis_engine}\n\n"
        "---\n\n"
    )

    for index, article in enumerate(articles):
        published = datetime.fromisoformat(article["published"]).strftime(
            "%b %d, %I:%M %p %Z"
        )
        summary = summaries[index] if index < len(summaries) else {}
        role_text = role_why.get(index, {})
        why_it_matters = role_text.get("why_it_matters", role_config["fallback"])
        role_impact = role_text.get("business_impact", summary.get("business_impact", "Review required."))

        content += (
            f"## {article['source']}: {article['headline']}\n\n"
            f"**Published:** {published}\n\n"
            f"**What happened:** {summary.get('what_happened', 'N/A')}\n\n"
            f"**Why it matters:** {why_it_matters}\n\n"
            f"**Business impact:** {role_impact}\n\n"
        )

        related_urls = article.get("related_urls") or [article["url"]]
        content += "**Sources:**\n\n"
        for url in related_urls:
            content += f"- {url}\n"
        content += "\n---\n\n"

    content += (
        "## Summary\n\n"
        f"- **Role:** {role_config['label']}\n"
        f"- **Total items:** {len(articles)}\n"
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}\n"
    )

    briefing_file = BRIEFING_DIR / f"{today}.{role_config['file_suffix']}.md"
    briefing_file.parent.mkdir(parents=True, exist_ok=True)
    briefing_file.write_text(content, encoding="utf-8")

    print(f"Role briefing written to {briefing_file}")
    return briefing_file


def generate_rss_feed():
    """Generate an RSS feed containing the ten most recent briefings."""
    files = sorted(BRIEFING_DIR.glob("*.md"), reverse=True)

    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")

    ET.SubElement(channel, "title").text = "Banking Regulatory Briefing"
    ET.SubElement(channel, "link").text = (
        "https://github.com/filimentation/regulatory-briefing"
    )
    ET.SubElement(channel, "description").text = (
        "Daily banking regulatory news for banking professionals"
    )
    ET.SubElement(channel, "language").text = "en-us"

    for briefing_file in files[:10]:
        date_str = briefing_file.stem

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"Regulatory Briefing - {date_str}"
        )
        ET.SubElement(item, "link").text = (
            "https://github.com/filimentation/regulatory-briefing/"
            f"blob/main/briefings/{briefing_file.name}"
        )
        ET.SubElement(item, "description").text = (
            briefing_file.read_text(encoding="utf-8")[:500] + "..."
        )
        ET.SubElement(item, "pubDate").text = datetime.strptime(
            date_str.split(".")[-1] if "." in date_str else date_str,
            "%Y-%m-%d",
        ).strftime("%a, %d %b %Y 06:00:00 +0000")
        ET.SubElement(item, "guid").text = f"briefing-{date_str}"

    ET.ElementTree(root).write(
        Path("feed.xml"),
        encoding="utf-8",
        xml_declaration=True,
    )

    print("RSS feed generated: feed.xml")


def main():
    kagi_success = True
    claude_success = True

    if not KAGI_API_KEY:
        print(
            "ERROR: KAGI_API_KEY environment variable not set",
            file=sys.stderr,
        )
        return 1

    if not ANTHROPIC_API_KEY:
        print(
            "WARNING: ANTHROPIC_API_KEY environment variable not set; role briefings will be generated in limited mode.",
            file=sys.stderr,
        )
        claude_success = False

    print("Fetching regulatory news via Kagi...")
    articles = fetch_news_kagi(max_articles=40)

    if not articles:
        print("No articles found", file=sys.stderr)
        return 1

    print(f"Found {len(articles)} source articles")
    print("Consolidating coverage and generating briefing with Claude...")

    briefing_items, claude_success = generate_briefing_items(articles)
    consolidated_articles, summaries = build_consolidated_articles(
        articles,
        briefing_items,
    )

    print(f"Created {len(consolidated_articles)} consolidated briefing items")

    create_markdown_briefing(consolidated_articles, summaries, kagi_success, claude_success)
    role_why_by_role = generate_role_briefings(
        consolidated_articles,
        ROLE_CONFIGS,
        claude_success,
    )

    for role_key, role_config in ROLE_CONFIGS.items():
        create_role_markdown_briefing(
            role_key,
            role_config,
            consolidated_articles,
            summaries,
            role_why_by_role.get(role_key, {}),
            kagi_success,
            claude_success,
        )

    generate_rss_feed()
    print("\nBriefing complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
