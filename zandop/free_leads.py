"""Free, public business-site intake; no search-result scraping or email guessing."""
import re
from urllib.parse import urljoin, urlsplit

from .db import add_lead, connect, event
from .discovery import respect_robots
from .integrations import fetch_public
from .policy import Blocked
from .research import SiteParser


def inspect_sites(urls, service):
    results = []
    for url in urls[:12]:
        try:
            respect_robots(url)
            content, resolved = fetch_public(url)
            parser = SiteParser()
            parser.feed(content)
            pages = [(resolved, content)]
            for href in parser.links:
                target = urljoin(resolved, href)
                if urlsplit(target).hostname == urlsplit(resolved).hostname and re.search(r"contact|about", urlsplit(target).path, re.I) and target not in [page[0] for page in pages]:
                    respect_robots(target)
                    text, destination = fetch_public(target)
                    pages.append((destination, text))
                    if len(pages) == 3:
                        break
            contacts = []
            for source, html in pages:
                page = SiteParser()
                page.feed(html)
                values = [href[7:].split("?")[0] for href in page.links if href.lower().startswith("mailto:")]
                values += re.findall(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", " ".join(page.text))
                for address in values:
                    address = address.strip().lower()
                    if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address) and not address.endswith(("@example.com", ".png", ".jpg", ".webp")) and address not in [item[0] for item in contacts]:
                        contacts.append((address, source))
            if not contacts:
                results.append({"url": url, "status": "needs_contact", "detail": "No published email found on the inspected pages. Review the business contact page manually."})
                continue
            address, source = contacts[0]
            with connect() as db:
                existing = db.execute("SELECT id FROM leads WHERE email=? AND demo=0", (address,)).fetchone()
                if existing:
                    results.append({"url": url, "status": "existing", "lead_id": existing[0]})
                    continue
                lead = add_lead(db, {"name": (parser.title.strip() or urlsplit(resolved).hostname)[:120], "email": address, "website": resolved, "service": service, "source": "manual", "details": {"outreach_candidate": True, "contact_source": source}})
                event(db, lead["id"], "Lead Finder", "public_contact.found", "Published business contact found; research and first-email review still required")
                results.append({"url": url, "status": "imported", "lead_id": lead["id"], "email": address})
        except Exception as exc:
            detail = str(exc) if isinstance(exc, Blocked) else "This business site could not be inspected. Review it manually."
            results.append({"url": url, "status": "needs_review", "detail": detail})
            with connect() as db:
                event(db, None, "Lead Finder", "site.review_needed", detail)
    return {"results": results}
