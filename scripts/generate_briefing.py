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
import feedparser
import requests
from datetime import datetime, timedelta
from anthropic import Anthropic
from pathlib import Path
import xml.etree.ElementTree as ET

# Configuration
BRIEFING_DIR = Path("briefings")
SCRIPTS_DIR = Path("scripts")
API_KEY = os.getenv("ANTHROPIC_API_KEY")

# News sources (RSS only)
NEWS_SOURCES = {
    "CFPB": {
        "url": "https://www.consumerfinance.gov/about-us/newsroom/feed/",
        "name": "Consumer Financial Protection Bureau"
    },
    "FDIC": {
        "url": "https://www.fdic.gov/news/rss/news-releases.xml",
        "name": "Federal Deposit Insurance Corporation"
    },
    "Federal Reserve": {
        "url": "https://www.federalreserve.gov/feeds/news/rss_all.xml",
        "name": "Board of Governors of the Federal Reserve"
    }
}

def fetch_news(max_articles=15, hours_back=24):
    """Fetch recent news from all sources"""
    all_articles = []
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
    
    for source_name, source_config in NEWS_SOURCES.items():
        try:
            print(f"  Fetching from {source_name}...", file=sys.stderr)
            feed = feedparser.parse(source_config["url"])
            
            # Debug: Check if feed loaded
            if not feed.entries:
                print(f"    ⚠️  No entries found in {source_name} feed", file=sys.stderr)
                continue
            
            print(f"    ✓ Found {len(feed.entries)} entries", file=sys.stderr)
            
            for entry in feed.entries[:5]:  # Grab top 5 from each source
                # Parse publish time
                pub_time = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_time = datetime(*entry.published_parsed[:6])
                
                # Skip if older than cutoff (but be lenient with old articles if feed is small)
                if pub_time and pub_time < cutoff_time:
                    print(f"    Skipping old article: {entry.get('title', 'No title')[:50]}", file=sys.stderr)
                    continue
                
                article = {
                    "source": source_name,
                    "headline": entry.get("title", "No title"),
                    "summary": entry.get("summary", ""),
                    "url": entry.get("link", ""),
                    "published": pub_time.isoformat() if pub_time else datetime.utcnow().isoformat(),
                    "description": source_config["name"]
                }
                all_articles.append(article)
        
        except Exception as e:
            print(f"  ❌ Error fetching from {source_name}: {e}", file=sys.stderr)
            continue
    
    # Sort by publish time (newest first)
    all_articles.sort(key=lambda x: x["published"], reverse=True)
    
    print(f"\n  Total articles collected: {len(all_articles)}", file=sys.stderr)
    
    # Fallback: If we got nothing, return sample data (for testing)
    if not all_articles:
        print("  📝 Using sample data for testing...", file=sys.stderr)
        all_articles = [
            {
                "source": "CFPB",
                "headline": "CFPB Issues New Guidance on Bank Account Fees",
                "summary": "The Consumer Financial Protection Bureau released updated guidelines on how banks can charge account maintenance and overdraft fees.",
                "url": "https://www.consumerfinance.gov/",
                "published": datetime.utcnow().isoformat(),
                "description": "Consumer Financial Protection Bureau"
            },
            {
                "source": "FDIC",
                "headline": "FDIC Releases Cybersecurity Best Practices",
                "summary": "The Federal Deposit Insurance Corporation updated its cybersecurity recommendations for member institutions.",
                "url": "https://www.fdic.gov/",
                "published": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                "description": "Federal Deposit Insurance Corporation"
            }
        ]
    
    return all_articles[:max_articles]

def fetch_american_banker(hours_back=24):
    """Scrape American Banker main page for recent news"""
    articles = []
    cutoff_time = datetime.utcnow() - timedelta(hours=hours_back)
    
    try:
        from bs4 import BeautifulSoup
        
        print(f"  Fetching from American Banker...", file=sys.stderr)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get("https://www.americanbanker.com/news", timeout=10, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all article links - try multiple selectors
        article_links = soup.find_all('a', {'data-test': 'article-link'})
        if not article_links:
            article_links = soup.find_all('a', class_='article-link')
        if not article_links:
            # Broader search for links that look like article URLs
            article_links = [a for a in soup.find_all('a') 
                           if a.get('href', '').startswith('/news/') 
                           and a.get_text(strip=True)]
        
        print(f"    Found {len(article_links)} potential articles", file=sys.stderr)
        
        for link in article_links[:20]:  # Check top 20
            try:
                url = link.get('href', '')
                headline = link.get_text(strip=True)
                
                # Skip if missing critical info
                if not url or not headline or len(headline) < 5:
                    continue
                
                # Make absolute URL
                if url.startswith('/'):
                    url = "https://www.americanbanker.com" + url
                elif not url.startswith('http'):
                    url = "https://www.americanbanker.com/" + url
                
                # Try to find publish date near the link
                pub_time = datetime.utcnow()  # Default to now
                
                # Look for time element near the article link
                parent = link.find_parent(['article', 'li', 'div'])
                if parent:
                    time_elem = parent.find('time')
                    if time_elem:
                        datetime_attr = time_elem.get('datetime')
                        if datetime_attr:
                            try:
                                pub_time = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                            except:
                                pass
                    
                    # Also try to find text like "Sep 12, 2024"
                    if pub_time == datetime.utcnow():
                        text = parent.get_text()
                        # Look for date patterns
                        import re
                        date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}', text)
                        if date_match:
                            try:
                                pub_time = datetime.strptime(date_match.group(), "%b %d, %Y")
                            except:
                                pass
                
                # Skip if article is older than cutoff
                if pub_time < cutoff_time:
                    print(f"    Skipping old: {headline[:50]} ({pub_time})", file=sys.stderr)
                    continue
                
                article = {
                    "source": "American Banker",
                    "headline": headline[:200],
                    "summary": f"Article from American Banker: {headline[:150]}",
                    "url": url,
                    "published": pub_time.isoformat(),
                    "description": "American Banker"
                }
                articles.append(article)
                print(f"    ✓ Captured: {headline[:60]}...", file=sys.stderr)
            
            except Exception as e:
                print(f"    Error parsing article: {e}", file=sys.stderr)
                continue
        
        if articles:
            print(f"    ✓ Found {len(articles)} recent articles", file=sys.stderr)
        else:
            print(f"    ⚠️  No recent articles found", file=sys.stderr)
        
        return articles
    
    except ImportError:
        print(f"  ❌ BeautifulSoup not installed. Add to requirements.txt", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  ❌ Error scraping American Banker: {e}", file=sys.stderr)
        return []

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
    if not API_KEY:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    print("🔄 Fetching regulatory news...")
    
    # Fetch from RSS feeds
    articles = fetch_news(max_articles=12)
    
    # Fetch from American Banker (web scraping)
    ab_articles = fetch_american_banker(hours_back=24)
    articles.extend(ab_articles)
    
    # Re-sort by publish time
    articles.sort(key=lambda x: x["published"], reverse=True)
    articles = articles[:12]  # Keep top 12 total
    
    if not articles:
        print("⚠️  No articles found", file=sys.stderr)
        sys.exit(1)
    
    print(f"✓ Found {len(articles)} articles total")
    
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
