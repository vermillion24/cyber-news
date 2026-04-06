import os
import requests
import feedparser
import resend
import time
import random
import tweepy
from datetime import datetime
from dotenv import load_dotenv
from google import genai
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
# --- 1. CONFIGURATION & API KEYS ---
load_dotenv()  # This loads the variables from .env into os.environ
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
TO_EMAIL = os.environ.get('TO_EMAIL')

# Initialize Clients
client = genai.Client(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY

# List of high-value Security RSS feeds
RSS_FEEDS = {
    "Cloudflare": "https://blog.cloudflare.com/rss/",
    "Fortinet": "https://www.fortinet.com/blog/rss-feeds/psirt-blogs.xml",
    "Cisco Talos": "https://blog.talosintelligence.com/rss/",
    "Microsoft Security": "https://www.microsoft.com/en-us/security/blog/feed/",
    "CISA Advisories": "https://www.cisa.gov/cybersecurity-advisories/all.xml",
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    "The Hacker News": "https://feeds.feedburner.com/TheHackersNews",
    "Krebs on Security": "https://krebsonsecurity.com/feed/"
}

# --- 2. NEW FEATURE: RESILIENT FETCHING ---
def get_safe_session():
    """Creates a session that automatically retries on temporary network failures."""
    session = requests.Session()
    retries = Retry(
        total=3, 
        backoff_factor=1, 
        status_forcelist=[429, 500, 502, 503, 504]
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def fetch_all_sources():
    all_articles = []
    session = get_safe_session()
    print("Fetching RSS feeds...")
    
    # Fetch from specific Company RSS Feeds
    for company, url in RSS_FEEDS.items():
        try:
            # Added timeout and user-agent to prevent hanging or blocking
            response = session.get(url, timeout=(5, 15), headers={
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
            response.raise_for_status()
            
            feed = feedparser.parse(response.text)
            for entry in feed.entries[:3]:  # Limit to top 3 newest per source
                all_articles.append({
                    "source": company,
                    "title": entry.title,
                    "description": entry.get('summary', 'No summary available'),
                    "link": entry.link
                })
        except Exception as e:
            print(f"Error fetching {company}: {e}")

    print("Fetching NewsAPI data...")
    query = "(cybersecurity OR 'data breach' OR ransomware OR 'zero-day' OR malware) AND (vulnerability OR patch OR exploit)"
    news_url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}"
    
    try:
        response = session.get(news_url, timeout=(5, 15))
        response.raise_for_status()
        news_data = response.json()
        if news_data.get('status') == 'ok':
            for a in news_data.get('articles', [])[:10]:
                all_articles.append({
                    "source": a['source']['name'],
                    "title": a['title'],
                    "description": a['description'],
                    "link": a['url']
                })
    except Exception as e:
        print(f"NewsAPI error: {e}")

    return all_articles

# --- 3. AI CONTENT GENERATION (REFINED PROMPT) ---
def generate_article(articles):
    print("Generating article with Gemini...")
    
    context_text = ""
    for a in articles:
        context_text += f"SOURCE: {a['source']}\nTITLE: {a['title']}\nSUMMARY: {a['description']}\nLINK: {a['link']}\n---\n"
    
    prompt = f"""
    ROLE: You are a Senior Cyber Security Researcher and Technical Journalist.
    
    TASK: Analyze the provided raw data and write a 'Daily Cyber Intelligence Brief' for a technical audience.
    
    CONSTRAINTS:
    - DO NOT use marketing fluff or "corporate speak."
    - DO NOT summarize articles that are just product advertisements.
    - FOCUS on vulnerabilities, exploits, patches, and threat actor activity.
    - If a CVE ID is mentioned in the data, it MUST be included in the summary.
    
    STRUCTURE:
    1. Main Headline: A single, high-impact headline for today's most critical news.
    2. The Big Story: Select the most technically significant event. Write 3 detailed paragraphs explaining the vulnerability, who is at risk, and the technical mechanism of the threat.
    3. Vendor Security Watch: Provide a bulleted list for updates from Cloudflare, Fortinet, Oracle, Cisco, and Microsoft. Each bullet should mention the specific product and the fix.
    4. Critical Headlines: 3-5 short bullets on other notable security news.
    5. Admin Priority List: A 'TL;DR' list of 3 specific actions (e.g., "Patch FortiOS to v7.x immediately").

    RAW DATA FOR ANALYSIS:
    {context_text}
    """
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-3-flash-preview',
                contents=prompt
            )
            return response.text
        except Exception as e:
            # If it's a 503 (Overloaded) error, wait and try again
            if "503" in str(e) or "unavailable" in str(e).lower():
                wait_time = (2 ** attempt) + random.random()
                print(f"[-] Gemini overloaded. Retrying in {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            else:
                print(f"[-] Permanent Gemini Error: {e}")
                return None
    
    print("[-] Failed to generate article after 3 attempts due to 503 errors.")
    return None
    
def send_email(content):
    print(f"Sending email to {TO_EMAIL} via Resend...")
    clean_content = content.replace('**', '')
    
    today_str = datetime.now().strftime('%B %d, %Y')
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; background-color: #f4f7f6; margin: 0; padding: 20px; }}
            .container {{ max-width: 700px; margin: auto; background: #ffffff; padding: 30px; border-radius: 10px; border: 1px solid #e1e4e8; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            .header {{ border-bottom: 3px solid #2c3e50; padding-bottom: 15px; margin-bottom: 25px; }}
            .header h2 {{ color: #2c3e50; margin: 0; font-size: 24px; }}
            .header span {{ color: #7f8c8d; font-size: 14px; }}
            .content-box {{ white-space: pre-wrap; font-size: 16px; color: #2c3e50; }}
            .footer {{ margin-top: 30px; padding-top: 15px; border-top: 1px solid #eee; font-size: 12px; color: #95a5a6; text-align: center; }}
            .action-hint {{ background: #fff3cd; border-left: 5px solid #ffecb5; padding: 10px; margin-top: 20px; font-size: 14px; font-style: italic; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>🛡️ Cyber Intelligence Draft</h2>
                <span>Generated for: {today_str}</span>
            </div>
            
            <div class="content-box">
                {content}
            </div>

            <div class="action-hint">
                <strong>Reviewer Note:</strong> This draft was compiled from Cloudflare, Fortinet, Oracle, and NewsAPI. Review for technical accuracy before publishing to the site.
            </div>

            <div class="footer">
                Automated Cyber News System | Powered by Gemini-3-Flash & GitHub Actions
            </div>
        </div>
    </body>
    </html>
    """
    
    params = {
        "from": "CyberBot <onboarding@resend.dev>",
        "to": [TO_EMAIL],
        "subject": f"DRAFT: Cyber Briefing - {today_str}",
        "html": html_body
    }

    try:
        email = resend.Emails.send(params)
        print(f"Success! Email sent. ID: {email['id']}")
    except Exception as e:
        print(f"Resend error: {e}")

def update_web_article(content):
    print("Generating Professional Markdown Post...")
    
    # 1. Hugo looks in content/posts/ for news
    os.makedirs('content/posts', exist_ok=True)
    
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    file_path = f"content/posts/{date_str}.md"
    
    # Hugo the Title and Date of the post
    markdown_output = f"""---
title: "Cyber Intel Brief: {now.strftime('%B %d, %Y')}"
date: "{now.isoformat()}"
author: "CyberBot"
draft: false
toc: true
---

{content}

---
### 📬 Subscribe & Connect
Stay updated on the latest threats. 
[View GitHub Repo](https://github.com/vermillion24/cyber-news) | [LinkedIn](https://www.linkedin.com/in/YOUR_PROFILE)
"""

    # 3. Write the file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(markdown_output)
        
    print(f"[+] Saved successfully to {file_path}")

def post_to_buffer(title, link):
    """
    Sends the daily brief to Buffer's GraphQL API.
    """
    api_key = os.getenv("BUFFER_ACCESS_TOKEN")
    channel_ids = ["69d42ae6031bfa423cd7876f"] 

    endpoint = "https://api.buffer.com"
    
    # STABLE QUERY: Uses fragments and handles the schema
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    
    clean_title = title.replace('**', '').strip()
    message = f"🛡️ New Cyber Intelligence Brief 🛡️\n\nTopic: {clean_title}\n\nRead more: {link}\n#InfoSec #CyberSecurity"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for c_id in channel_ids:
        variables = {
            "input": {
                "text": message,
                "channelId": c_id,
                "schedulingType": "automatic",
                "mode": "shareNow"
            }
        }

        try:
            print(f"Pushing to Buffer channel: {c_id}...")
            response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers)
            
            # Defensive check for non-JSON responses
            if response.status_code != 200:
                print(f"❌ HTTP Error {response.status_code}: {response.text}")
                continue

            data = response.json()
            
            # Check for structural GraphQL errors
            if "errors" in data:
                print(f"❌ GraphQL Validation Error: {data['errors'][0]['message']}")
            elif "data" in data and "createPost" in data["data"]:
                result = data["data"]["createPost"]
                if "message" in result:
                    print(f"❌ Buffer Logic Error: {result['message']}")
                else:
                    print(f"✅ Post Successful! ID: {result['post']['id']}")
        
        except Exception as e:
            print(f"❌ Script Error: {e}")
        
# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Get news
    news_items = fetch_all_sources()
    
    if not news_items:
        print("No news items found. Exiting.")
    else:
        print(f"[+] Collected {len(news_items)} total items.")
        
        # Generate content (Gemini Call)
        article = generate_article(news_items)
        
        if article:
            # Send to your inbox
            send_email(article)
            
            # Generate the Markdown post for Hugo
            update_web_article(article)
            
            # Extract a dynamic title for the Tweet
            # first line of the Gemini output as the headline
            lines = article.strip().split('\n')
            dynamic_title = lines[0].replace('#', '').strip() # Cleans up Markdown headers
            
            # Post to Social via Buffer
            site_url = "https://vermillion24.github.io/cyber-news/"
            post_to_buffer(dynamic_title, site_url)
            
            print("[+] All tasks completed successfully. Ready for Hugo build.")
        else:
            print("!!! Failed to generate article content.")
