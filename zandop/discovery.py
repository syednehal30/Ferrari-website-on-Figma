"""Public/authorized source ingestion. No login automation or access-control bypass."""
import csv
import io
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .integrations import fetch_public
from .policy import Blocked, require_live


def respect_robots(url):
    host = urlsplit(url)
    robots_url = f"{host.scheme}://{host.netloc}/robots.txt"
    try:
        text, _ = fetch_public(robots_url)
    except Exception as exc:
        import httpx
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
            return
        raise Blocked("Could not establish crawler permission from robots.txt.") from None
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    if not parser.can_fetch("ZanDopResearch", url):
        raise Blocked("This source disallows automated access in robots.txt. Use an authorized export or API.")


class StructuredDirectory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.scripts = []
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active = True
            self.buffer = []

    def handle_data(self, text):
        if self.active:
            self.buffer.append(text)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.scripts.append("".join(self.buffer))
            self.active = False


def flatten(value):
    if isinstance(value, list):
        for item in value:
            yield from flatten(item)
    elif isinstance(value, dict):
        if value.get("name") and value.get("email"):
            yield value
        for key in ["@graph", "itemListElement", "item", "hiringOrganization"]:
            if key in value:
                yield from flatten(value[key])


def discover_source(url, kind, service):
    require_live()
    if kind not in {"shopify_directory", "woocommerce_directory", "job_board", "linkedin"}:
        raise Blocked("Unsupported discovery source.")
    respect_robots(url)
    raw, _ = fetch_public(url)
    if urlsplit(url).path.endswith(".csv"):
        candidates = list(csv.DictReader(io.StringIO(raw)))
    else:
        try:
            candidates = list(flatten(json.loads(raw)))
        except json.JSONDecodeError:
            parser = StructuredDirectory()
            parser.feed(raw)
            candidates = []
            for script in parser.scripts:
                try:
                    candidates.extend(flatten(json.loads(script)))
                except json.JSONDecodeError:
                    continue
    results = []
    for candidate in candidates[:100]:
        email = str(candidate.get("email", "")).removeprefix("mailto:").strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            continue
        results.append({"name": str(candidate.get("name", ""))[:120], "email": email,
                        "website": str(candidate.get("website") or candidate.get("url") or "")[:2000],
                        "platform": "Shopify" if kind == "shopify_directory" else "WooCommerce" if kind == "woocommerce_directory" else str(candidate.get("platform", ""))[:60],
                        "industry": str(candidate.get("industry", ""))[:120], "service": service, "source": kind})
    return results
