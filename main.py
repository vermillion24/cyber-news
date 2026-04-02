import os
import requests
import feedparser
import resend
import time
import random
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
    
    # NEW REFINED PROMPT
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
    
# --- 4. EMAIL DELIVERY (REFINED TEMPLATE) ---
def send_email(content):
    print(f"Sending email to {TO_EMAIL} via Resend...")
    clean_content = content.replace('**', '')
    
    # Get current date for the subject and header
    today_str = datetime.now().strftime('%B %d, %Y')
    
    # This template creates a professional "Newsletter" feel in your inbox
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
    print("Archiving the article and updating the home page...")
    
    # Setup dates and paths
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    display_date = now.strftime('%B %d, %Y')
    
    # 1. Ensure the news directory exists
    if not os.path.exists('news'):
        os.makedirs('news')
    
    # 2. Create the unique daily file (The Archive)
    # We use MVP.css here for a clean, professional look
    daily_filename = f"news/{date_str}.html"
    clean_content = content.replace('**', '')

    daily_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Cyber Intel - {display_date}</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/water.css@2/out/dark.css">
        <style>
            /* Adding a tiny bit of custom 'Cyber' flair */
            body { max-width: 900px; line-height: 1.6; }
            h1, h2 { color: #00ff41; font-family: 'Courier New', Courier, monospace; } /* Matrix Green headers */
            header { border-bottom: 1px solid #444; margin-bottom: 20px; }
            footer { margin-top: 50px; border-top: 1px solid #444; padding-top: 20px; }
            a { color: #3498db; }
        </style>
    </head>
    <body>
        <header>
            <nav>
                <a href="../index.html">⬅ Back to Home</a>
            </nav>
            <h1>🛡️ Intel Briefing: {display_date}</h1>
        </header>
        <main>
            <section style="white-space: pre-wrap;">{clean_content}</section>
        </main>
    </body>
    </html>
    """
    
    with open(daily_filename, "w", encoding="utf-8") as f:
        f.write(daily_html)

    # 3. Update index.html (The Home Page / Master List)
    # We add your LinkedIn and GitHub Star button here
    github_repo = "vermillion24/cyber-news"
    linkedin_url = "https://www.linkedin.com/in/YOUR_PROFILE" # Update this!

    index_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Cyber Intelligence Archive</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/water.css@2/out/dark.css">
        <style>
            /* Adding a tiny bit of custom 'Cyber' flair */
            body { max-width: 900px; line-height: 1.6; }
            h1, h2 { color: #00ff41; font-family: 'Courier New', Courier, monospace; } /* Matrix Green headers */
            header { border-bottom: 1px solid #444; margin-bottom: 20px; }
            footer { margin-top: 50px; border-top: 1px solid #444; padding-top: 20px; }
            a { color: #3498db; }
        </style>
    </head>
    <body>
        <header>
            <h1>🛡️ Cyber Intelligence Hub</h1>
            <p>Automated daily threat research and vulnerability analysis.</p>
        </header>
        <main>
            <section>
                <h2>Latest Briefing</h2>
                <p>Read the most recent update: <a href="{daily_filename}">Update for {display_date}</a></p>
            </section>
            <hr>
            <footer>
                <h3>Connect & Support</h3>
                <p>
                    <a href="{linkedin_url}">LinkedIn Profile</a> | 
                    <a href="https://github.com/{github_repo}">View on GitHub</a>
                </p>
                <iframe src="https://ghbtns.com/github-btn.html?user={github_repo.split('/')[0]}&repo={github_repo.split('/')[1]}&type=star&count=true&size=large" frameborder="0" scrolling="0" width="170" height="30" title="GitHub"></iframe>
            </footer>
        </main>
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
        
# --- 5. MAIN EXECUTION ---
if __name__ == "__main__":
    from datetime import datetime
    
    # Step 1: Get news with retry logic
    news_items = fetch_all_sources()
    
    if not news_items:
        print("No news items found. Exiting.")
    else:
        print(f"[+] Collected {len(news_items)} total items.")
        
        # Step 2: Generate content (Gemini Call)
        article = generate_article(news_items)
        
        if article:
            # Step 3: Action 1 - Send to your inbox for review
            send_email(article)
            
            # Step 4: Action 2 - Update the index.html for your website
            update_web_article(article)
            
            print("[+] All tasks completed successfully.")
        else:
            print("!!! Failed to generate article content.")
