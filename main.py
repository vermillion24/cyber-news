from dotenv import load_dotenv
load_dotenv()  # This loads the variables from .env into os.environ
import os
import requests
import feedparser
import resend
from google import genai

# --- 1. CONFIGURATION & API KEYS ---
# These are pulled from GitHub Secrets (or your local .env file)
load_dotenv()  # Ensure this is called to load environment variables
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
TO_EMAIL = os.environ.get('TO_EMAIL')

# Initialize Resend
client = genai.Client(api_key=GEMINI_API_KEY)
resend.api_key = RESEND_API_KEY

# List of high-value Security RSS feeds
RSS_FEEDS = {
    "Cloudflare": "https://blog.cloudflare.com/rss/",
    "Fortinet": "https://www.fortinet.com/rss/threat-research.xml",
    "Oracle": "https://blogs.oracle.com/security/rss",
    "Cisco Talos": "https://blog.talosintelligence.com/feeds/posts/default",
    "Microsoft Security": "https://www.microsoft.com/en-us/security/blog/feed/",
    "Mandiant": "https://www.mandiant.com/resources/blog/rss.xml"
}

# --- 2. DATA FETCHING ---
def fetch_all_sources():
    all_articles = []
    print("Fetching RSS feeds...")
    
    # Fetch from specific Company RSS Feeds
    for company, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
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
    # Fetch broad tech news (Google, Apple, Amazon, etc.)
    query = "(Google Cloud OR AWS OR Apple Security) AND (vulnerability OR 'zero-day' OR patch)"
    news_url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&language=en&apiKey={NEWS_API_KEY}"
    
    try:
        response = requests.get(news_url)
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

# --- 3. AI CONTENT GENERATION ---
def generate_article(articles):
    print("Generating article with Gemini...")
    
    # Format the collected news for the AI
    context_text = ""
    for a in articles:
        context_text += f"SOURCE: {a['source']}\nTITLE: {a['title']}\nSUMMARY: {a['description']}\n---\n"
    
    prompt = f"""
    You are a Lead Cyber Security Journalist. I have provided a list of raw news items from major tech companies.
    
    TASK: Write a cohesive Daily Cyber News Briefing for my website.
    
    STRUCTURE:
    1. A bold, engaging main headline for the day.
    2. 'The Big Story': Choose the most impactful incident and write 3 detailed paragraphs.
    3. 'Vendor Watch': Summarize specific updates/patches from companies like Cloudflare, Fortinet, or Oracle.
    4. 'Brief Headlines': A bulleted list of other notable tech news.
    5. 'Expert Take': A 2-sentence summary of what IT admins should prioritize today.

    Use professional, technical, yet clear language. Format with clear headings.

    RAW DATA:
    {context_text}
    """
    
    try:
        # THE FIX: Use 'gemini-1.5-flash' (no models/ prefix) with the new Client
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt
        )
        return response.text
    except Exception as e:
        # If it still fails, this will print the specific reason
        print(f"Gemini API error: {e}")
        return None
    
# --- 4. EMAIL DELIVERY ---
def send_email(content):
    print(f"Sending email to {TO_EMAIL} via Resend...")
    
    # Simple formatting: Replace newlines with HTML breaks for the email
    html_body = f"""
    <h2>Daily Cyber News Draft</h2>
    <hr>
    <div style="font-family: sans-serif; line-height: 1.6;">
        {content.replace('\n', '<br>')}
    </div>
    """
    
    params = {
        "from": "CyberBot <onboarding@resend.dev>",
        "to": [TO_EMAIL],
        "subject": f"Draft: Cyber News for {datetime.now().strftime('%Y-%m-%d')}",
        "html": html_body
    }

    try:
        email = resend.Emails.send(params)
        print(f"Success! Email sent. ID: {email['id']}")
    except Exception as e:
        print(f"Resend error: {e}")

# --- 5. MAIN EXECUTION ---
if __name__ == "__main__":
    from datetime import datetime
    
    # Step 1: Get news
    news_items = fetch_all_sources()
    
    if not news_items:
        print("No news items found. Exiting.")
    else:
        # Step 2: Generate content
        article = generate_article(news_items)
        
        if article:
            # Step 3: Send to your inbox
            send_email(article)
        else:
            print("Failed to generate article content.")