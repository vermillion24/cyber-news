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
load_dotenv()
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
TO_EMAIL = os.environ.get('TO_EMAIL')

# Initialize Clients
client = genai.Client(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY

# RSS feeds
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

# --- 2.FETCHING ---
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
    ROLE: You are a Senior Cyber Security Researcher. 
    
    TASK: Write a 'Daily Cyber Intelligence Brief' based on the raw data below.
    
    CRITICAL STYLE LOGIC:
    - OMIT any vendor from the 'Vendor Security Watch' if there is no specific news or patch for them today. Do NOT say "No updates reported."
    - DO NOT mention "the provided data," "the dataset," or "sources." Write as if you are reporting this news firsthand.
    - Use clean Markdown. Use '###' for subheaders.
    
    STRUCTURE:
    1. Main Headline: High-impact.
    2. The Big Story: 3 technical paragraphs (Mechanism, Impact, Remediation).
    3. Vendor Security Watch: Bullet points for specific fixes (only for vendors with active news).
    4. Critical Headlines: 3-5 short bullets on other news.
    5. Admin Priority List: 3 actionable steps.

    (End the response with the marker '### Social Hook' followed by the catchy summary and hashtags.)

    RAW DATA:
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
    print("Uploading Intelligence Brief to SecIntel API...")
    
    API_URL = "https://secintel.net/api/news"
    API_TOKEN = os.environ.get('API_AUTH_TOKEN')
    
    lines = content.strip().split('\n')
    title = lines[0].replace('#', '').strip()
    
    payload = {
        "title": title,
        "content": content,
        "date": datetime.now().isoformat()
    }
    
    try:
        headers = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json"
        }
        response = requests.post(API_URL, json=payload, headers=headers)

        #Debugging
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text[:1000]}")
        
        response.raise_for_status()
        
        # Get the ID sent back by the worker
        result = response.json()
        article_id = result.get('id')
        
        print(f"[+] Successfully posted! Article ID: {article_id}")
        return article_id
        
    except Exception as e:
        print(f"[-] Failed to update web database: {e}")
        return None
def post_to_buffer(article_content, link):
    """
    Post to social media through buffer schema
    """
    api_key = os.getenv("BUFFER_ACCESS_TOKEN")
    channel_ids = ["69d42ae6031bfa423cd7876f","69e9f765031bfa423c349404"] 
    endpoint = "https://api.buffer.com"

    clean_article = article_content.replace('**', '').replace('#', '').strip()

    # --- EXTRACTION LOGIC ---
    if "Social Hook:" in clean_article:
        social_text = clean_article.split("Social Hook:")[-1].strip()
    else:
        # Fallback: Take the first two sentences of the article
        lines = clean_article.split('\n')
        social_text = lines[0] if lines else "New Cyber Intelligence Briefing Available."

    if len(social_text) > 200:
        social_text = social_text[:197] + "..."

    # --- MESSAGE ---
    final_message = (
        f"🚨 {social_text}\n\n"
        f"🔗 Read Full Report:\n"
        f"{link}"
    )

    # --- GRAPHQL EXECUTION ---
    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }
    """

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    for c_id in channel_ids:
        variables = {
            "input": {
                "text": final_message, 
                "channelId": c_id,
                "schedulingType": "automatic",
                "mode": "shareNow"
            }
        }

        try:
            print(f"Pushing to Buffer: {c_id}...")
            response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers)
            data = response.json()
            
            if "errors" in data:
                print(f"❌ GraphQL Error: {data['errors'][0]['message']}")
            else:
                print(f"✅ Success! Post sent to {c_id}")
        except Exception as e:
            print(f"❌ Script Error: {e}")
            
# --- MAIN EXECUTION ---
if __name__ == "__main__":
    news_items = fetch_all_sources()
    
    if news_items:
        full_response = generate_article(news_items)
        
        if full_response:
            # avoid "too many values to unpack"
            parts = full_response.split("### Social Hook", 1)
            
            if len(parts) == 2:
                web_content = parts[0].strip()
                social_content = parts[1].strip()
            else:
                web_content = full_response.strip()
                social_content = "Latest updates in Kenyan & Global Cyber Security."

                # 2. Upload to Website and GET the ID
            article_id = update_web_article(web_content)
            
            if article_id:
                article_url = f"https://secintel.net/resources?newsId={article_id}"
            else:
                article_url = "https://secintel.net/resources"
            
            send_email(web_content)
            post_to_buffer(social_content, article_url)
            
            print(f"[+] All tasks completed. Posted to Social: {article_url}")
