import requests
from bs4 import BeautifulSoup

URL = "https://wodboxtraining.aimharder.com"


def fetch_info(url):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e)}

    soup = BeautifulSoup(resp.text, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta_desc_tag = soup.find("meta", attrs={"name": "description"})
    meta_desc = meta_desc_tag["content"].strip() if meta_desc_tag and meta_desc_tag.get("content") else None

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text().strip()
        links.append({"href": href, "text": text})

    return {"url": url, "title": title, "meta_description": meta_desc, "links_count": len(links), "links_sample": links[:10]}


if __name__ == "__main__":
    info = fetch_info(URL)
    if "error" in info:
        print("Error al acceder:", info["error"])
    else:
        print("URL:", info["url"])
        print("Título:", info["title"])
        print("Meta descripción:", info["meta_description"])
        print("Número de enlaces:", info["links_count"])
        print("Muestra de enlaces:")
        for link in info["links_sample"]:
            print(f"- {link['text']} -> {link['href']}")
