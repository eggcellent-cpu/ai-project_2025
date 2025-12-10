# scrape_urls_products.py

import csv
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

INPUT_URL_CSV = "all_product_urls.csv"
OUTPUT_CSV = "products_other_visual_dataset.csv"


# ----------------- Helpers ----------------- #

def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "amazon." in host:
        return "amazon"
    if "lazada." in host:
        return "lazada"
    if "ebay." in host:
        return "ebay"
    return "other"


def safe_goto(page, url: str, timeout: int = 25000):
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
    except Exception:
        try:
            page.goto(url, timeout=timeout, wait_until="load")
        except Exception as e:
            print(f"   [ERROR] failed to load {url}: {e}")


def soup_from_page(page):
    return BeautifulSoup(page.content(), "lxml")


def get_og_title_and_image(soup):
    title = ""
    img = ""

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        img = og_image["content"].strip()

    return title, img


def pad_images(imgs, max_n=4):
    imgs = [i for i in imgs if i]
    imgs = imgs[:max_n]
    while len(imgs) < max_n:
        imgs.append("")
    return imgs


def classify_product_type(title: str) -> str:
    if not title:
        return "Other"

    t = title.lower()

    printer_keywords = [
        "printer", "laserjet", "inkjet", "multifunction",
        "all-in-one", "mfp"
    ]

    toner_keywords = [
        "toner", "drum unit", "laser cartridge",
        "toner cartridge"
    ]

    ink_keywords = [
        "ink", "ink bottle", "ink tank",
        "ink cartridge"
    ]

    if any(k in t for k in printer_keywords):
        return "Printer"
    if any(k in t for k in toner_keywords):
        return "Toner"
    if any(k in t for k in ink_keywords):
        return "Ink"

    return "Other"


# ----------------- AMAZON ----------------- #

def scrape_amazon(page, url):
    safe_goto(page, url, timeout=30000)
    # shorter sleep, rely mostly on DOMContentLoaded
    page.wait_for_timeout(1200)
    soup = soup_from_page(page)

    title, og_img = get_og_title_and_image(soup)

    if not title:
        el = soup.select_one("#productTitle")
        if el:
            title = el.get_text(strip=True)

    imgs = []
    main = soup.select_one("img#landingImage")
    if main:
        src = main.get("src") or ""
        if src:
            imgs.append(src)

    if main and main.get("data-a-dynamic-image"):
        import json
        try:
            js = json.loads(main["data-a-dynamic-image"])
            for k in js.keys():
                imgs.append(k)
        except Exception:
            pass

    if og_img and og_img not in imgs:
        imgs.append(og_img)

    return title, pad_images(imgs)


# ----------------- LAZADA ----------------- #

def scrape_lazada(page, url):
    safe_goto(page, url, timeout=30000)
    page.wait_for_timeout(1800)
    soup = soup_from_page(page)

    title, og_img = get_og_title_and_image(soup)
    if not title and soup.title:
        title = soup.title.string.strip()

    imgs = []
    for img in soup.find_all("img"):
        src = img.get("src") or ""
        low = src.lower()
        if "slatic.net" in low or "lazada" in low:
            if "sprite" in low or "logo" in low:
                continue
            imgs.append(src)

    if og_img:
        imgs.insert(0, og_img)

    return title, pad_images(imgs)


# ----------------- EBAY ----------------- #

def scrape_ebay(page, url):
    safe_goto(page, url, timeout=30000)
    page.wait_for_timeout(1200)
    soup = soup_from_page(page)

    title, og_img = get_og_title_and_image(soup)

    if not title:
        selectors = [
            "h1.x-item-title__mainTitle span.ux-textspans--BOLD",
            "h1.x-item-title__mainTitle",
            "h1[itemprop='name']",
            "h1",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                title = el.get_text(strip=True)
                break

    imgs = []

    active = soup.select_one("div.ux-image-carousel-item.active img")
    if active and active.get("src"):
        imgs.append(active["src"])

    for img in soup.find_all("img"):
        src = img.get("src") or ""
        if "i.ebayimg.com" in src:
            imgs.append(src)

    if og_img:
        imgs.insert(0, og_img)

    imgs = list(dict.fromkeys(imgs))  # dedupe

    return title, pad_images(imgs)


# ----------------- GENERIC ----------------- #

def scrape_generic(page, url):
    safe_goto(page, url, timeout=25000)
    page.wait_for_timeout(1000)
    soup = soup_from_page(page)

    title, og_img = get_og_title_and_image(soup)
    if not title and soup.title:
        title = soup.title.string.strip()

    imgs = [
        img.get("src")
        for img in soup.find_all("img")
        if img.get("src", "").startswith("http")
    ]

    if og_img:
        imgs.insert(0, og_img)

    return title, pad_images(imgs)


# ----------------- MAIN RUNNER ----------------- #

def main():
    with open(INPUT_URL_CSV, newline="", encoding="utf-8") as f:
        url_rows = [row for row in csv.DictReader(f) if row.get("URL")]

    rows_out = []
    seen_keys = set()   # to dedupe by (source, brand, title)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(25000)

        for idx, row in enumerate(url_rows, 1):
            url = row["URL"]
            source = (row.get("Source") or domain_of(url)).strip()
            brand = row.get("Brand", "").strip()

            print(f"[{idx}/{len(url_rows)}] {source.upper():7} {url}")

            try:
                if source == "amazon":
                    title, imgs = scrape_amazon(page, url)
                elif source == "lazada":
                    title, imgs = scrape_lazada(page, url)
                elif source == "ebay":
                    title, imgs = scrape_ebay(page, url)
                else:
                    title, imgs = scrape_generic(page, url)

            except Exception as e:
                print("   [ERROR scraping]", e)
                continue

            if not any(imgs):
                print("   [WARN] No images found → skipping")
                continue

            product_type = classify_product_type(title)

            # keep only Printer / Toner / Ink
            if product_type == "Other":
                print("   [SKIP] Not printer/toner/ink based on title.")
                continue

            key = (source, brand, title.strip())
            if key in seen_keys:
                print("   [SKIP] Duplicate product (same source/brand/title)")
                continue
            seen_keys.add(key)

            print("   title:", title)
            print("   type :", product_type)
            print("   imgs :", imgs)

            rows_out.append({
                "URL": url,
                "Source": source,
                "Brand": brand,
                "Product_ID": f"{source}_{brand}_{idx:03d}",
                "Product_Title": title,
                "Product_Type": product_type,
                "Image_URL_1": imgs[0],
                "Image_URL_2": imgs[1],
                "Image_URL_3": imgs[2],
                "Image_URL_4": imgs[3],
            })

        browser.close()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "URL", "Source", "Brand", "Product_ID",
            "Product_Title", "Product_Type",
            "Image_URL_1", "Image_URL_2",
            "Image_URL_3", "Image_URL_4",
        ])
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\n✅ Done. Saved {len(rows_out)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
