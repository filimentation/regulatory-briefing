#!/usr/bin/env python3
"""
Daily Regulatory Briefing Generator
Fetches news from CFPB, FDIC, Federal Reserve, American Banker
Generates ELI15 summaries using Claude API
Outputs markdown file and updates RSS feed
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta
from anthropic import Anthropic
from pathlib import Path
import xml.etree.ElementTree as ET

# Configuration
BRIEFING_DIR = Path("briefings")
SCRIPTS_DIR = Path("scripts")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
KAGI_API_KEY = os.getenv("KAGI_API_KEY")
KAGI_API_URL = "https://kagi.com/api/v1/search"

# News sources - Kagi will search for these
NEWS_SOURCES = {
    "CFPB": {
        "query": "site:consumerfinance.gov news",
        "name": "Consumer Financial Protection Bureau"
    },
    "FDIC": {
        "query": "site:fdic.gov news",
        "name": "Federal Deposit Insurance Corporation"
    },
    "Federal Reserve": {
        "query": "site:federalreserve.gov news",
        "name": "Federal Reserve"
    },
    "American Banker": {
        "query": "site:americanbanker.com news",
        "name": "American Banker"
    }
}

def fetch_news_kagi(max_articles=15, hours_back=24):
    """Fetch recent news from all sources using Kagi API"""
    all_articles = []
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
    
    if not KAGI_API_KEY:
        print("ERROR: KAGI_API_KEY environment variable not set", file=sys.stderr)
        return []
    
    for source_name, source_config in NEWS_SOURCES.items():
        try:
            print(f"  Searching {source_name}...", file=sys.stderr)
            
            payload = {
                "query": source_config["query"],
                "workflow": "news",
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {KAGI_API_KEY}",
            }
            
            response = requests.post("https://kagi.com/api/v1/search", json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            
            results = response.json()
            
            if "data" not in results or "results" not in results["data"]:
                print(f"    ⚠️  No results found", file=sys.stderr)
                continue
            
            search_results = results["data"]["results"]
            print(f"    ✓ Found {len(search_results)} results", file=sys.stderr)
            
            for result in search_results[:5]:  # Take top 5 from each source
                try:
                    headline = result.get("title", "No title")
                    url = result.get("url", "")
                    summary = result.get("snippet", "")
                    
                    # Try to extract publish date from result metadata
                    pub_time = datetime.utcnow()  # Default to now
                    
                    # Kagi includes "published" field if available
                    if "published" in result:
                        try:
                            pub_time = datetime.fromisoformat(
                                result["published"].replace("Z", "+00:00")
                            )
                        except:
                            pass
                    
                    # Skip very old articles
                    if pub_time < cutoff_time:
                        print(f"    Skipping old: {headline[:50]}", file=sys.stderr)
                        continue
                    
                    if not url or not headline:
                        continue
                    
                    article = {
                        "source": source_name,
                        "headline": headline[:200],
                        "summary": summary[:300] if summary else headline[:150],
                        "url": url,
                        "published": pub_time.isoformat(),
                        "description": source_config["name"]
                    }
                    all_articles.append(article)
                    print(f"    ✓ {headline[:60]}...", file=sys.stderr)
                
                except Exception as e:
                    print(f"    Error parsing result: {e}", file=sys.stderr)
                    continue
        
        except Exception as e:
            print(f"  ❌ Error querying {source_name}: {e}", file=sys.stderr)
            continue
    
    # Sort by publish time (newest first)
    all_articles.sort(key=lambda x: x["published"], reverse=True)
    
    print(f"\n  Total articles found: {len(all_articles)}", file=sys.stderr)
    
    return all_articles[:max_articles]

def generate_eli15_summary(article):
    """Use Claude API to generate ELI15 summary"""
    client = Anthropic()
    
    prompt = f"""You are writing a financial news briefing for banking professionals.
Explain this regulatory/banking news at an ELI15 level (explain like I'm 15).

IMPORTANT: This means:
- Use plain language, but assume the reader knows what banks do
- Explain the "why" not just the "what"
- Flag any business impact for a bank employee
- Skip jargon OR define it inline when unavoidable
- Keep to 2-3 sentences MAX for each section

Article headline: {article['headline']}
Article source: {article['source']}
Article summary: {article['summary']}

Respond in this exact JSON format (and ONLY JSON, no markdown, no backticks):
{{
  "what_happened": "plain language summary of the news",
  "why_it_matters": "specific impact for banking/compliance",
  "business_impact": "one-line impact (e.g. 'Medium - Affects compliance reporting')"
}}"""
    
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        response_text = message.content[0].text
        # Clean up any markdown code fences
        response_text = response_text.replace("```json", "").replace("```", "").strip()
        result = json.loads(response_text)
        return result
    
    except Exception as e:
        print(f"Error generating summary for '{article['headline']}': {e}", file=sys.stderr)
        return {
            "what_happened": article['summary'][:200],
            "why_it_matters": "See original article for details",
            "business_impact": "Review required"
        }

def create_markdown_briefing(articles, summaries):
    """Create markdown file for today's briefing"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    md_content = f"""# Regulatory Briefing - {datetime.now().strftime("%B %d, %Y")}

**Generated:** {datetime.now().strftime("%I:%M %p %Z")}

---

"""
    
    for article, summary in zip(articles, summaries):
        pub_time = datetime.fromisoformat(article["published"]).strftime("%b %d, %I:%M %p %Z")
        
        md_content += f"""## {article['source']}: {article['headline']}

**Published:** {pub_time}

**What happened:** {summary.get('what_happened', 'N/A')}

**Why it matters:** {summary.get('why_it_matters', 'N/A')}

**Business impact:** {summary.get('business_impact', 'Review required')}

**Read more:** [{article['source']} article]({article['url']})

---

"""
    
    # Add summary stats
    md_content += f"""## Summary

- **Total items:** {len(articles)}
- **Sources:** {', '.join(set(a['source'] for a in articles))}
- **Generated:** {datetime.now().isoformat()}
"""
    
    # Write to file
    briefing_file = BRIEFING_DIR / f"{today}.md"
    briefing_file.parent.mkdir(exist_ok=True)
    briefing_file.write_text(md_content)
    
    print(f"✓ Briefing written to {briefing_file}")
    return briefing_file

def generate_rss_feed():
    """Generate RSS feed from all briefing markdown files"""
    briefing_files = sorted(BRIEFING_DIR.glob("*.md"), reverse=True)
    
    rss_root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss_root, "channel")
    
    ET.SubElement(channel, "title").text = "Banking Regulatory Briefing"
    ET.SubElement(channel, "link").text = "https://github.com"
    ET.SubElement(channel, "description").text = "Daily ELI15 regulatory news for banking professionals"
    ET.SubElement(channel, "language").text = "en-us"
    
    for briefing_file in briefing_files[:10]:  # Last 10 days
        # Parse the markdown file
        content = briefing_file.read_text()
        date_str = briefing_file.stem
        
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"Regulatory Briefing - {date_str}"
        ET.SubElement(item, "link").text = f"https://github.com/YOUR_USERNAME/regulatory-briefing/blob/main/briefings/{briefing_file.name}"
        ET.SubElement(item, "description").text = content[:500] + "..."  # First 500 chars
        ET.SubElement(item, "pubDate").text = datetime.strptime(date_str, "%Y-%m-%d").strftime("%a, %d %b %Y 06:00:00 +0000")
        ET.SubElement(item, "guid").text = f"briefing-{date_str}"
    
    # Write RSS feed
    rss_file = Path("feed.xml")
    tree = ET.ElementTree(rss_root)
    tree.write(rss_file, encoding="utf-8", xml_declaration=True)
    
    print(f"✓ RSS feed generated: {rss_file}")

def main():
    """Main execution"""
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    if not KAGI_API_KEY:
        print("ERROR: KAGI_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    print("🔄 Fetching regulatory news via Kagi...")
    articles = fetch_news_kagi(max_articles=12)
    
    if not articles:
        print("⚠️  No articles found", file=sys.stderr)
        sys.exit(1)
    
    print(f"✓ Found {len(articles)} articles")
    
    print("🤖 Generating ELI15 summaries with Claude...")
    summaries = []
    for i, article in enumerate(articles, 1):
        print(f"  [{i}/{len(articles)}] {article['source']}: {article['headline'][:50]}...")
        summary = generate_eli15_summary(article)
        summaries.append(summary)
    
    print("✓ Summaries generated")
    
    print("📝 Creating markdown briefing...")
    create_markdown_briefing(articles, summaries)
    
    print("📡 Generating RSS feed...")
    generate_rss_feed()
    
    print("\n✅ Briefing complete!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
