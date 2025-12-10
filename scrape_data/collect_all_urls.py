# collect_all_product_urls.py

from playwright.sync_api import sync_playwright
import csv
import time

BRANDS = ["Brother", "Canon", "Epson", "HP", "Ricoh", "Samsung", "Xerox"]

# We will search 3 product types per brand
QUERY_TYPES = ["printer", "toner", "ink"]

AMAZON_SEARCH = "https://www.amazon.sg/s?k={brand}+{qtype}"
LAZADA_SEARCH = "https://www.lazada.sg/catalog/?q={brand}%20{qtype}"
EBAY_SEARCH   = "https://www.ebay.com/sch/i.html?_nkw={brand}+{qtype}"

OUTPUT_URL_CSV = "all_product_urls.csv"

# how many product URLs per (brand, qtype, source)
MAX_PRODUCTS_PER_QUERY = 60


# ---------------------------
#  COMMON UTILITIES
# ---------------------------
def safe_goto(page, url, timeout=30000):
    """Load URL with fallback logic to avoid crashes."""
    print(f"  → GOTO {url}")
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        try:
            page.goto(url, timeout=timeout, wait_until="load")
        except Exception:
            print("  ⚠️ FAILED TO LOAD:", url)


def scroll_down(page, steps=10, pause=800):
    """Scroll to force SPA sites (like Lazada) to load more items."""
    for _ in range(steps):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(pause)


# ---------------------------
#  AMAZON
# ---------------------------
def collect_amazon_urls(page, brand, qtype, max_products=MAX_PRODUCTS_PER_QUERY):
    url = AMAZON_SEARCH.format(brand=brand, qtype=qtype)
    safe_goto(page, url)
    page.wait_for_timeout(2500)

    links = set()

    anchors = page.query_selector_all(
        "a.a-link-normal.s-underline-text.s-underline-link-text"
    )
    if not anchors:
        anchors = page.query_selector_all("a.a-link-normal.s-no-outline")

    print(f"  Amazon ({qtype}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if "/dp/" in href:
            full = "https://www.amazon.sg" + href.split("?")[0]
            links.add(full)
        if len(links) >= max_products:
            break

    print(f"  Amazon ({qtype}): collected {len(links)} product URLs for {brand}")
    return list(links)


# ---------------------------
#  LAZADA
# ---------------------------
def collect_lazada_urls(page, brand, qtype, max_products=MAX_PRODUCTS_PER_QUERY):
    url = LAZADA_SEARCH.format(brand=brand, qtype=qtype)
    safe_goto(page, url)
    page.wait_for_timeout(3000)

    scroll_down(page, steps=15, pause=500)

    links = set()
    anchors = page.query_selector_all("a[href*='/products/']")

    print(f"  Lazada ({qtype}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue

        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.lazada.sg" + href

        clean = href.split("?")[0]
        links.add(clean)

        if len(links) >= max_products:
            break

    print(f"  Lazada ({qtype}): collected {len(links)} product URLs for {brand}")
    return list(links)


# ---------------------------
#  EBAY
# ---------------------------
def collect_ebay_urls(page, brand, qtype, max_products=MAX_PRODUCTS_PER_QUERY):
    url = EBAY_SEARCH.format(brand=brand, qtype=qtype)
    safe_goto(page, url)
    page.wait_for_timeout(2000)

    links = set()
    anchors = page.query_selector_all("a.s-item__link")

    if not anchors:
        anchors = page.query_selector_all("a[href*='/itm/']")

    if not anchors:
        print(f"  ⚠️ eBay ({qtype}): no product anchors found for {brand}")
        return []

    print(f"  eBay ({qtype}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if "/itm/" in href:
            clean = href.split("?")[0]
            links.add(clean)
        if len(links) >= max_products:
            break

    print(f"  eBay ({qtype}): collected {len(links)} product URLs for {brand}")
    return list(links)


# ---------------------------
#  MAIN
# ---------------------------
def main():
    rows = []
    seen_urls = set()   # avoid duplicates across all sources/brands

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page()

        for brand in BRANDS:
            print("\n==============================")
            print(f"     BRAND: {brand}")
            print("==============================")

            for qtype in QUERY_TYPES:
                print(f"\n----- QUERY: {qtype.upper()} -----")

                # AMAZON
                print("=== Amazon ===")
                for u in collect_amazon_urls(page, brand, qtype):
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    print("  Amazon:", u)
                    rows.append({
                        "URL": u,
                        "Source": "amazon",
                        "Brand": brand,
                        "QueryType": qtype,
                    })

                # LAZADA
                print("=== Lazada ===")
                for u in collect_lazada_urls(page, brand, qtype):
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    print("  Lazada:", u)
                    rows.append({
                        "URL": u,
                        "Source": "lazada",
                        "Brand": brand,
                        "QueryType": qtype,
                    })

                # EBAY
                print("=== eBay ===")
                for u in collect_ebay_urls(page, brand, qtype):
                    if u in seen_urls:
                        continue
                    seen_urls.add(u)
                    print("  eBay  :", u)
                    rows.append({
                        "URL": u,
                        "Source": "ebay",
                        "Brand": brand,
                        "QueryType": qtype,
                    })

                # brief pause between query types
                time.sleep(1.5)

        browser.close()

    # Write CSV
    with open(OUTPUT_URL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Source", "Brand", "QueryType"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ SAVED {len(rows)} UNIQUE URLs → {OUTPUT_URL_CSV}")


if __name__ == "__main__":
    main()
