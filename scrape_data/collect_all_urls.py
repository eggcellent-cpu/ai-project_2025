# collect_all_product_urls.py

from playwright.sync_api import sync_playwright
from urllib.parse import quote_plus
import csv
import time

# ---------------------------
#  CONFIG
# ---------------------------

BRANDS = ["Brother", "Canon", "Epson", "HP", "Ricoh", "Samsung", "Xerox"]
QUERY_TYPES = ["printer", "toner", "ink"]

# Fine-grained keywords for variety
QUERY_VARIANTS = {
    "printer": [
        "printer",
        "laser printer",
        "inkjet printer",
        "all in one printer",
        "wireless printer",
    ],
    "toner": [
        "toner",
        "toner cartridge",
        "laser toner",
        "drum unit",
    ],
    "ink": [
        "ink",
        "ink cartridge",
        "ink bottle",
        "ink tank",
        "photo printer ink",
    ],
}

# Search templates
AMAZON_SEARCH = "https://www.amazon.sg/s?k={query}"
EBAY_SEARCH = "https://www.ebay.com/sch/i.html?_nkw={query}"
LAZADA_SEARCH = "https://www.lazada.sg/catalog/?q={query}"
CHALLENGER_SEARCH = "https://www.challenger.sg/search?q={query}"

OUTPUT_URL_CSV = "all_product_urls.csv"

# Max per keyword per source
MAX_PRODUCTS_PER_VARIANT_PER_SOURCE = 40

# NEW: Only keep reliable sources
ALLOWED_SOURCES = {"amazon", "ebay", "challenger", "lazada"}

# NEW: Stop when balanced dataset is ready
TARGET_PER_CLASS = {
    "printer": 1000,
    "toner": 1000,
    "ink": 1000,
}


# ---------------------------
#  UTILITIES
# ---------------------------

def safe_goto(page, url, timeout=20000):
    print(f"  → GOTO {url}")
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        try:
            page.goto(url, timeout=timeout, wait_until="load")
        except Exception:
            print("  ⚠ FAILED:", url)


def scroll_down(page, steps=8, pause=400):
    for _ in range(steps):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(pause)


# ---------------------------
#  AMAZON
# ---------------------------

def collect_amazon_urls(page, brand, keyword, max_products):
    query = quote_plus(f"{brand} {keyword}")
    url = AMAZON_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(1200)

    links = set()
    anchors = page.query_selector_all("a.a-link-normal.s-no-outline") or \
              page.query_selector_all("a.a-link-normal")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if "/dp/" in href:
            full = "https://www.amazon.sg" + href.split("?")[0]
            links.add(full)
        if len(links) >= max_products:
            break

    return list(links)


# ---------------------------
#  EBAY
# ---------------------------

def collect_ebay_urls(page, brand, keyword, max_products):
    query = quote_plus(f"{brand} {keyword}")
    url = EBAY_SEARCH.format(query=query)
    safe_goto(page, url)

    try:
        page.wait_for_load_state("networkidle")
    except:
        page.wait_for_timeout(1500)

    links = set()
    anchors = page.query_selector_all("a.s-item__link") or \
              page.query_selector_all("a[href*='/itm/']")

    for a in anchors:
        href = a.get_attribute("href")
        if href and "/itm/" in href:
            links.add(href.split("?")[0])
        if len(links) >= max_products:
            break

    return list(links)


# ---------------------------
#  LAZADA
# ---------------------------

def collect_lazada_urls(page, brand, keyword, max_products):
    query = quote_plus(f"{brand} {keyword}")
    url = LAZADA_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(2000)

    scroll_down(page, steps=10, pause=350)

    anchors = page.query_selector_all("a[href*='/products/']")
    links = set()

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.lazada.sg" + href

        links.add(href.split("?")[0])
        if len(links) >= max_products:
            break

    return list(links)


# ---------------------------
#  CHALLENGER
# ---------------------------

def collect_challenger_urls(page, brand, keyword, max_products):
    query = quote_plus(f"{brand} {keyword}")
    url = CHALLENGER_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(2500)

    scroll_down(page, steps=8, pause=350)

    anchors = page.query_selector_all("a[href*='/products/'], a[href*='/product/']")
    links = set()

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if href.startswith("/"):
            href = "https://www.challenger.sg" + href
        links.add(href.split("?")[0])
        if len(links) >= max_products:
            break

    return list(links)


# ---------------------------
#  MAIN SCRAPER
# ---------------------------

def main():
    rows = []
    seen = set()

    # New counters for balanced dataset
    class_counts = {k: 0 for k in TARGET_PER_CLASS}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(20000)

        for brand in BRANDS:
            print("\n==============================")
            print(f"      BRAND: {brand}")
            print("==============================\n")

            for qtype in QUERY_TYPES:
                print(f"--- QUERY TYPE: {qtype.upper()} ---")
                variants = QUERY_VARIANTS[qtype]

                for keyword in variants:

                    # stop early if full dataset collected
                    if all(class_counts[t] >= TARGET_PER_CLASS[t] for t in TARGET_PER_CLASS):
                        print("\n🎉 Reached target dataset size — stopping early.")
                        browser.close()
                        return save_csv(rows)

                    print(f"\n🔍 keyword = {keyword}")
                    cap = MAX_PRODUCTS_PER_VARIANT_PER_SOURCE

                    # AMAZON
                    for url in collect_amazon_urls(page, brand, keyword, cap):
                        if add_row(url, "amazon", brand, qtype, rows, seen, class_counts):
                            pass

                    # EBAY
                    for url in collect_ebay_urls(page, brand, keyword, cap):
                        if add_row(url, "ebay", brand, qtype, rows, seen, class_counts):
                            pass

                    # LAZADA
                    for url in collect_lazada_urls(page, brand, keyword, cap):
                        if add_row(url, "lazada", brand, qtype, rows, seen, class_counts):
                            pass

                    # CHALLENGER
                    for url in collect_challenger_urls(page, brand, keyword, cap):
                        if add_row(url, "challenger", brand, qtype, rows, seen, class_counts):
                            pass

                    time.sleep(0.7)

        browser.close()

    save_csv(rows)


# ---------------------------
#  HELPERS
# ---------------------------

def add_row(url, source, brand, qtype, rows, seen, class_counts):
    key = (url, source)
    if key in seen:
        return False

    seen.add(key)
    class_counts[qtype] += 1

    rows.append({
        "URL": url,
        "Source": source,
        "Brand": brand,
        "QueryType": qtype,
    })

    return True


def save_csv(rows):
    with open(OUTPUT_URL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["URL", "Source", "Brand", "QueryType"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ SAVED {len(rows)} URLs → {OUTPUT_URL_CSV}")


if __name__ == "__main__":
    main()
