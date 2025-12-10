# collect_all_product_urls.py

from playwright.sync_api import sync_playwright
from urllib.parse import quote_plus
import csv
import time

# ---------------------------
#  CONFIG
# ---------------------------

BRANDS = ["Brother", "Canon", "Epson", "HP", "Ricoh", "Samsung", "Xerox"]

# High-level product types you still care about
QUERY_TYPES = ["printer", "toner", "ink"]

# More fine-grained variants per query type for visual variety
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

# Search URL templates for each source
AMAZON_SEARCH      = "https://www.amazon.sg/s?k={query}"
EBAY_SEARCH        = "https://www.ebay.com/sch/i.html?_nkw={query}"
ALIEXPRESS_SEARCH  = "https://www.aliexpress.com/wholesale?SearchText={query}"
HARVEY_SEARCH      = "https://www.harveynorman.com.sg/search?q={query}"
CHALLENGER_SEARCH  = "https://www.challenger.sg/search?q={query}"

OUTPUT_URL_CSV = "all_product_urls.csv"

# Cap per (brand, keyword, source)
MAX_PRODUCTS_PER_VARIANT_PER_SOURCE = 50


# ---------------------------
#  COMMON UTILITIES
# ---------------------------

def safe_goto(page, url, timeout=20000):
    """Load URL with fallback logic to avoid crashes."""
    print(f"  → GOTO {url}")
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        try:
            page.goto(url, timeout=timeout, wait_until="load")
        except Exception:
            print("  ⚠️ FAILED TO LOAD:", url)


def scroll_down(page, steps=8, pause=400):
    """Scroll to force SPA / infinite-scroll sites to load more items."""
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
    page.wait_for_timeout(1500)

    links = set()

    anchors = page.query_selector_all(
        "a.a-link-normal.s-underline-text.s-underline-link-text"
    )
    if not anchors:
        anchors = page.query_selector_all("a.a-link-normal.s-no-outline")

    print(f"  Amazon ({keyword}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if "/dp/" in href:
            full = "https://www.amazon.sg" + href.split("?")[0]
            links.add(full)
        if len(links) >= max_products:
            break

    print(f"  Amazon ({keyword}): collected {len(links)} product URLs for {brand}")
    return list(links)


# ---------------------------
#  EBAY
# ---------------------------

def collect_ebay_urls(page, brand, keyword, max_products):
    from playwright.sync_api import Error  # safe to import here

    query = quote_plus(f"{brand} {keyword}")
    url = EBAY_SEARCH.format(query=query)
    safe_goto(page, url)

    # Let the page fully settle if possible
    try:
        page.wait_for_load_state("networkidle")
    except Error:
        # fallback – not fatal
        page.wait_for_timeout(2000)

    links = set()

    try:
        anchors = page.query_selector_all("a.s-item__link")
    except Error as e:
        print(f"  ⚠ eBay ({keyword}): query_selector_all failed due to navigation: {e}")
        return []

    if not anchors:
        try:
            anchors = page.query_selector_all("a[href*='/itm/']")
        except Error as e:
            print(f"  ⚠ eBay ({keyword}): fallback selector also failed: {e}")
            return []

    if not anchors:
        print(f"  ⚠ eBay ({keyword}): no product anchors found for {brand}")
        return []

    print(f"  eBay ({keyword}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        if "/itm/" in href:
            clean = href.split("?")[0]
            links.add(clean)
        if len(links) >= max_products:
            break

    print(f"  eBay ({keyword}): collected {len(links)} product URLs for {brand}")
    return list(links)



# ---------------------------
#  ALIEXPRESS
# ---------------------------

def collect_aliexpress_urls(page, brand, keyword, max_products):
    """
    AliExpress search:
    - We look for product anchors with '/item/' in href.
    - Normalise to https://www.aliexpress.com/...
    """
    query = quote_plus(f"{brand} {keyword}")
    url = ALIEXPRESS_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(2500)

    # Scroll to load more cards
    scroll_down(page, steps=8, pause=400)

    links = set()
    anchors = page.query_selector_all("a[href*='/item/']")

    print(f"  AliExpress ({keyword}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue

        # AliExpress sometimes gives protocol-relative or relative URLs
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.aliexpress.com" + href

        clean = href.split("?")[0]

        # Light sanity check
        if "aliexpress.com/item" not in clean:
            continue

        links.add(clean)

        if len(links) >= max_products:
            break

    print(f"  AliExpress ({keyword}): collected {len(links)} product URLs for {brand}")
    return list(links)


def collect_harvey_urls(page, brand, keyword, max_products):
    """
    Harvey Norman SG:
    - Product URLs often end with `.html`, not necessarily `/products/`.
    - We'll:
        1) Grab all <a> that link to .html product pages
        2) Filter by brand / query keywords in URL or link text
    """
    query = quote_plus(f"{brand} {keyword}")
    url = HARVEY_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(2500)

    scroll_down(page, steps=6, pause=400)

    links = set()
    # broader selector: any product-ish link ending with .html
    anchors = page.query_selector_all("a[href$='.html']")

    print(f"  Harvey Norman ({keyword}): found {len(anchors)} anchors before filtering")

    wanted_terms = [brand.lower(), "printer", "toner", "ink"]

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue

        # normalise URL
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.harveynorman.com.sg" + href

        clean = href.split("?")[0]

        # quick filter: must be on harveynorman and end with .html
        if "harveynorman.com.sg" not in clean:
            continue

        # check text & href for relevant terms
        text = (a.inner_text() or "").lower()
        haystack = clean.lower() + " " + text

        if not any(term in haystack for term in wanted_terms):
            continue

        links.add(clean)

        if len(links) >= max_products:
            break

    print(f"  Harvey Norman ({keyword}): collected {len(links)} product URLs for {brand}")
    return list(links)


# ---------------------------
#  CHALLENGER (SG)
# ---------------------------

def collect_challenger_urls(page, brand, keyword, max_products):
    """
    Challenger SG:
    - Product URLs often contain '/products/' or '/product/'.
    - We grab both patterns and normalise.
    """
    query = quote_plus(f"{brand} {keyword}")
    url = CHALLENGER_SEARCH.format(query=query)
    safe_goto(page, url)
    page.wait_for_timeout(2500)

    scroll_down(page, steps=6, pause=400)

    links = set()
    anchors = page.query_selector_all("a[href*='/products/'], a[href*='/product/']")

    print(f"  Challenger ({keyword}): found {len(anchors)} anchors before filtering")

    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue

        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = "https://www.challenger.sg" + href

        clean = href.split("?")[0]

        if "/product" not in clean:
            continue

        links.add(clean)

        if len(links) >= max_products:
            break

    print(f"  Challenger ({keyword}): collected {len(links)} product URLs for {brand}")
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
        page.set_default_timeout(20000)

        for brand in BRANDS:
            print("\n==============================")
            print(f"     BRAND: {brand}")
            print("==============================")

            for qtype in QUERY_TYPES:
                print(f"\n----- QUERY TYPE: {qtype.upper()} -----")
                variants = QUERY_VARIANTS.get(qtype, [qtype])

                for keyword in variants:
                    print(f"\n  🔍 keyword: {keyword}")
                    per_variant_cap = MAX_PRODUCTS_PER_VARIANT_PER_SOURCE

                    # AMAZON
                    print("  === Amazon ===")
                    for u in collect_amazon_urls(page, brand, keyword, per_variant_cap):
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        rows.append({
                            "URL": u,
                            "Source": "amazon",
                            "Brand": brand,
                            "QueryType": qtype,
                        })

                    # EBAY
                    print("  === eBay ===")
                    for u in collect_ebay_urls(page, brand, keyword, per_variant_cap):
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        rows.append({
                            "URL": u,
                            "Source": "ebay",
                            "Brand": brand,
                            "QueryType": qtype,
                        })

                    # ALIEXPRESS
                    print("  === AliExpress ===")
                    for u in collect_aliexpress_urls(page, brand, keyword, per_variant_cap):
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        rows.append({
                            "URL": u,
                            "Source": "aliexpress",
                            "Brand": brand,
                            "QueryType": qtype,
                        })

                    # HARVEY NORMAN
                    print("  === Harvey Norman ===")
                    for u in collect_harvey_urls(page, brand, keyword, per_variant_cap):
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        rows.append({
                            "URL": u,
                            "Source": "harvey_norman",
                            "Brand": brand,
                            "QueryType": qtype,
                        })

                    # CHALLENGER
                    print("  === Challenger ===")
                    for u in collect_challenger_urls(page, brand, keyword, per_variant_cap):
                        if u in seen_urls:
                            continue
                        seen_urls.add(u)
                        rows.append({
                            "URL": u,
                            "Source": "challenger",
                            "Brand": brand,
                            "QueryType": qtype,
                        })

                    # brief pause between variants to be nice to servers
                    time.sleep(0.7)

        browser.close()

    # Write CSV
    with open(OUTPUT_URL_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["URL", "Source", "Brand", "QueryType"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✅ SAVED {len(rows)} UNIQUE URLs → {OUTPUT_URL_CSV}")


if __name__ == "__main__":
    main()
