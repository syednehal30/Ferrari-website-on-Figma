import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin

from .integrations import fetch_public


class SiteParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.images, self.text = [], [], []
        self.viewport = False
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "img":
            self.images.append(attrs)
        if tag == "meta" and attrs.get("name", "").lower() == "viewport":
            self.viewport = True
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        self.text.append(data)
        if self.in_title:
            self.title += data


def research(lead):
    if lead["demo"]:
        return {"platform": lead["platform"], "product_count": 24 if lead["service"] == "ecommerce" else None,
                "pricing": ["$48", "$96"] if lead["service"] == "ecommerce" else [], "load_seconds": 4.2,
                "mobile_viewport": False, "flaw": "The mobile navigation overlaps the main call to action.",
                "evidence": "Illustrative demo research; no live site was inspected.", "competitors": lead["details"].get("competitors", []),
                "competitor_status": "Demo comparison", "traffic": "Unknown", "revenue": "Unknown", "visual_quality": "Demo: needs improvement"}
    if not lead["website"]:
        return {"platform": "No website supplied", "product_count": None, "pricing": [], "load_seconds": None,
                "mobile_viewport": None, "flaw": "No business website was listed in the supplied lead source.",
                "evidence": "Source listing only; verify before making a claim about the business.", "competitors": [],
                "competitor_status": "Competitor URLs needed", "traffic": "Unknown", "revenue": "Unknown", "visual_quality": "Not measured"}
    from .discovery import respect_robots
    respect_robots(lead["website"])
    started = time.monotonic()
    html, url = fetch_public(lead["website"])
    elapsed = round(time.monotonic() - started, 2)
    parser = SiteParser()
    parser.feed(html)
    lower = html.lower()
    platform = "Shopify" if "cdn.shopify.com" in lower or "shopify.theme" in lower else "WooCommerce" if "woocommerce" in lower else "WordPress" if "wp-content" in lower else "Custom / undetected"
    products = {link for link in parser.links if "/products/" in link or "/product/" in link}
    missing_alt = sum(not image.get("alt") for image in parser.images)
    flaw = "The page is missing a mobile viewport declaration." if not parser.viewport else f"{missing_alt} images on the inspected page have no alternative text." if missing_alt else f"The initial HTML request took {elapsed} seconds in this environment." if elapsed > 3 else None
    competitors = []
    for competitor in lead["details"].get("competitors", [])[:3]:
        respect_robots(competitor)
        content, destination = fetch_public(competitor)
        other = SiteParser()
        other.feed(content)
        competitors.append({"url": destination, "title": other.title[:200], "mobile_viewport": other.viewport})
    return {"platform": platform, "product_count": len(products) or None, "product_count_note": "Observed product links on one page; not total catalog size.",
            "pricing": sorted(set(re.findall(r"[$£€]\s?\d[\d,.]*", " ".join(parser.text))))[:12],
            "load_seconds": elapsed, "load_note": "Initial HTML response, not full browser LCP.", "mobile_viewport": parser.viewport,
            "flaw": flaw, "evidence": url, "competitors": competitors, "competitor_status": "Inspected supplied URLs" if competitors else "Competitor URLs needed",
            "traffic": lead["details"].get("traffic_estimate", "Unknown"), "revenue": lead["details"].get("revenue_estimate", "Unknown"), "visual_quality": "Requires browser review", "title": parser.title[:200]}


def score_lead(lead):
    details = lead["details"]
    # Missing estimates contribute no points. All component weights and evidence remain visible in CRM.
    revenue = min(25, max(0, int(details.get("revenue_score", 0))))
    traffic = min(25, max(0, int(details.get("traffic_score", 0))))
    platform = 20 if lead["platform"].lower() in {"shopify", "woocommerce", "wordpress"} else 10
    visual = min(30, max(0, int(details.get("visual_score", 0))))
    if not lead["website"]:
        visual = 30
    return {"revenue": revenue, "traffic": traffic, "platform": platform, "visual_opportunity": visual, "total": revenue + traffic + platform + visual}
