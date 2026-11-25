from bs4 import BeautifulSoup
import requests


# Standard headers to fetch a website
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
}


def extract_homepage(html):
    """Extract the title, full body text and original link targets from one response."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    links = [link["href"] for link in soup.find_all("a", href=True) if link["href"]]
    if soup.body:
        for irrelevant in soup.body(["script", "style", "img", "input"]):
            irrelevant.decompose()
        text = soup.body.get_text(separator="\n", strip=True)
    else:
        text = ""
    return title, text, links


def fetch_website_contents(url):
    """Return the Day 5 title and body preview, limited to 2,000 characters."""
    response = requests.get(url, headers=headers, timeout=20)
    title, text, _ = extract_homepage(response.content)
    return ((title or "No title found") + "\n\n" + text)[:2_000]


def fetch_website_links(url):
    """Return the raw href values as in Day 5."""
    response = requests.get(url, headers=headers, timeout=20)
    _, _, links = extract_homepage(response.content)
    return links
