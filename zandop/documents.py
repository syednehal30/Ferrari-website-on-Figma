import textwrap
from pathlib import Path

from reportlab.lib.colors import HexColor, Color
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_ROOT = Path(__file__).parent / "static" / "fonts"
pdfmetrics.registerFont(TTFont("ZanDop", str(FONT_ROOT / "OpenSans-Regular.ttf")))
pdfmetrics.registerFont(TTFont("ZanDop-Bold", str(FONT_ROOT / "OpenSans-Semibold.ttf")))

from .db import data_dir, event, now, uid

INK = HexColor("#24202c")
PURPLE = HexColor("#6450d8")
PAPER = HexColor("#f7f5f0")
ORANGE = HexColor("#ef9d70")


class Book:
    def __init__(self, path, client, kind, demo):
        self.canvas = Canvas(str(path), pagesize=(595, 842))
        self.canvas.setTitle(f"ZanDop | {client} | {kind}")
        self.canvas.setAuthor("ZanDop")
        self.client, self.kind, self.demo, self.page = client, kind, demo, 0

    def begin(self, dark=False):
        self.page += 1
        c = self.canvas
        c.setFillColor(INK if dark else PAPER)
        c.rect(0, 0, 595, 842, fill=1, stroke=0)
        c.setFillColor(PAPER if dark else INK)
        c.setFont("ZanDop-Bold", 24)
        c.drawString(44, 790, "ZanDop")
        c.setFont("ZanDop", 9)
        c.drawRightString(551, 796, "DIGITAL, WITH DIRECTION.")
        c.setStrokeColor(HexColor("#48414f") if dark else HexColor("#ddd8df"))
        c.line(44, 764, 551, 764)
        c.line(44, 55, 551, 55)
        c.setFont("ZanDop", 8)
        c.drawString(44, 36, "DEMONSTRATION / FICTIONAL CLIENT" if self.demo else f"{self.client[:40]} / {self.kind.upper()}")
        c.drawRightString(551, 36, f"ZANDOP  /  {self.page:02}")

    def text(self, text, x, y, size=11, width=490, color=INK, bold=False, leading=None, max_lines=None):
        c = self.canvas
        c.setFillColor(color)
        font = "ZanDop-Bold" if bold else "ZanDop"
        c.setFont(font, size)
        lines = []
        for paragraph in str(text).split("\n"):
            # Break unusually long tokens so a supplied URL cannot escape the page margins.
            safe = " ".join(part for token in paragraph.split() for part in textwrap.wrap(token, 70))
            lines.extend(simpleSplit(safe, font, size, width))
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(".") + "..."
        for line in lines:
            c.drawString(x, y, line)
            y -= leading or size * 1.5
        return y

    def section(self, number, heading, body, y):
        self.text(number, 44, y, 10, color=PURPLE, bold=True)
        self.text(heading, 80, y, 17, bold=True)
        return self.text(body, 80, y - 28, 11, width=459, max_lines=4) - 32

    def end(self):
        self.canvas.showPage()

    def save(self):
        self.canvas.save()


def create_document(db, lead, kind):
    existing = db.execute("SELECT * FROM documents WHERE lead_id=? AND kind=? ORDER BY version DESC LIMIT 1", (lead["id"], kind)).fetchone()
    version = existing["version"] + 1 if existing else 1
    document_id = uid("doc_")
    relative = f"documents/{document_id}.pdf"
    path = data_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    service = {"ecommerce": "E-commerce experience", "website": "Website development", "content": "Content & editorial"}[lead["service"]]
    title = {"welcome": "Your next chapter", "plan": "The project blueprint", "brief": "The opportunity brief", "proposal": "Project proposal draft"}[kind]
    book = Book(path, lead["name"], kind, bool(lead["demo"]))
    research = lead["details"].get("research", {})
    if kind == "brief":
        book.begin()
        book.text("RESEARCH / ONE-PAGE BRIEF", 44, 727, 10, color=PURPLE, bold=True)
        book.text(lead["name"], 44, 679, 30, bold=True, max_lines=2)
        entries = [
            ("01", "The business", f"{lead['industry']} | {service}\nPlatform: {research.get('platform', lead['platform'])}. Traffic: {research.get('traffic', 'Unknown')}. Revenue: {research.get('revenue', 'Unknown')}.") ,
            ("02", "The opportunity", str(research.get("flaw") or "No substantiated flaw detected. Further review required.")),
            ("03", "Commerce & performance", f"Observed product links: {research.get('product_count', 'Unknown')}. Observed prices: {', '.join(research.get('pricing', [])) or 'Not observed'}.\nHTML response: {research.get('load_seconds')} s. Mobile viewport: {research.get('mobile_viewport')}. Browser layout has not been verified."),
            ("04", "Competitive context", str(research.get("competitors") or "No competitor evidence supplied; comparison remains open.")[:300]),
            ("05", "Evidence & limits", str(research.get("evidence", "No evidence yet"))[:230] + "\nCounts describe one inspected page. Estimates are inputs, not verified revenue or traffic.")]
        y = 620
        for num, heading, body in entries:
            y = book.section(num, heading, body, y)
        book.end()
    else:
        book.begin(dark=True)
        c = book.canvas
        c.setFillColor(PURPLE)
        c.circle(485, 438, 143, stroke=0, fill=1)
        c.setFillColor(ORANGE)
        c.circle(485, 438, 80, stroke=0, fill=1)
        c.setFillColor(INK)
        c.rect(341, 438, 290, 145, stroke=0, fill=1)
        book.text(f"{kind.upper()} / {service.upper()}", 44, 710, 10, color=ORANGE, bold=True)
        cover = "A better digital\nchapter starts here." if kind == "welcome" else "A clear plan.\nA confident next step." if kind == "plan" else "Built around\nyour next chapter."
        book.text(cover, 44, 640, 43, width=505, color=PAPER, bold=True, leading=51)
        book.text("PREPARED ESPECIALLY FOR", 44, 300, 9, color=ORANGE, bold=True)
        book.text(lead["name"], 44, 262, 29, color=PAPER, bold=True, max_lines=2)
        book.text(f"{lead['industry'] or 'Your industry'} / {service}\nVersion {version:02} / Working document, subject to final approval", 44, 211, 11, color=HexColor("#c8c2d2"))
        book.end()
        book.begin()
        book.text("01 / THE PROJECT BRIEF" if kind == "plan" else "01 / THE BIG PICTURE", 44, 718, 10, color=PURPLE, bold=True)
        book.text("The direction.\nThe details that matter." if kind == "plan" else "Your ambition.\nOur starting point.", 44, 672, 32, bold=True, leading=41)
        intro = f"A working blueprint for {lead['name']}: {service.lower()} on {lead['platform'] or 'the selected platform'}, shaped by the discovery conversation." if kind == "plan" else f"Welcome, {lead['name']}. We are bringing strategy, craft, and a clear delivery process to your {service.lower()} project."
        book.text(intro, 44, 554, 14, width=490, max_lines=3)
        book.section("01", "What we understand", str(lead["details"].get("goals") or f"Create a clearer, more useful digital experience for customers in {lead['industry'] or 'your market'}."), 454)
        deliverables = {"ecommerce": f"A {lead['platform']} storefront scaffold, product import CSV, catalog layout, responsive concept preview, and setup handoff. Production integration follows scope confirmation.", "website": f"A {lead['platform']} implementation scaffold, page or screen structure, reusable visual styles, responsive concept preview, and setup handoff. Specific features follow the recorded brief.", "content": "An editorial brief, brand-voice-aligned draft, SEO keyword mapping, and a list of factual claims to verify. Final publication follows editorial approval."}[lead["service"]]
        book.section("02", "What we will make" if kind == "plan" else "Where we can make a difference", deliverables if kind == "plan" else str(research.get("flaw") or "We will confirm priorities together during discovery before choosing an implementation."), 342)
        acceptance = "Working links; clear responsive layouts; reviewed copy and factual claims; target-platform checks; and final human approval. Schedule and production scope are confirmed after reviewing dependencies."
        book.section("03", "How we will know it is ready" if kind == "plan" else "The voice we will protect", acceptance if kind == "plan" else str(lead["details"].get("brand_voice") or "Clear, confident, and helpful. We will refine the voice with your examples and feedback."), 218)
        book.end()
        book.begin()
        book.text("02 / THE ROAD AHEAD", 44, 718, 10, color=PURPLE, bold=True)
        book.text("Four milestones.\nOne clear direction." if kind == "plan" else "Less guesswork.\nMore forward motion.", 44, 670, 32, bold=True, leading=39)
        milestones = [
            ("01", "Discover & align", "Confirm goals, audience, existing assets, and success measures. Your video call shapes the brief."),
            ("02", "Shape the direction", "Build a focused project plan with pages, features, content needs, and agreed milestones."),
            ("03", "Make & refine", {"ecommerce": "Map the catalog, scaffold the storefront, and refine product and collection experiences.", "website": "Build the selected WordPress, React, custom website, or React Native screens from the agreed specification.", "content": "Develop the editorial outline, write to your brand voice, and check target keywords and factual claims."}[lead["service"]]),
            ("04", "Check & hand over", "Review links, responsive layouts, copy, and performance. Final human approval comes before client delivery or publication.")]
        y = 536
        for number, heading, body in milestones:
            y = book.section(number, heading, body, y)
        book.end()
        book.begin()
        book.text("03 / MAKE IT YOURS", 44, 718, 10, color=PURPLE, bold=True)
        book.text("A strong start\nis a shared effort.", 44, 670, 32, bold=True, leading=39)
        needed = {"ecommerce": "Product CSV, collection structure, brand assets, photography, shipping preferences, and access via collaborator invitations.", "website": "Page list, brand assets, approved copy, examples you like, and a clear list of required features. Use collaborator invitations for access.", "content": "Brand voice examples, audience personas, target keywords, factual source material, and an editorial priority list."}[lead["service"]]
        y = book.section("01", "What to bring", needed, 535)
        y = book.section("02", "Your project notes", str(lead["details"].get("call_notes") or "We will capture decisions after the discovery call and turn them into the next version of your project plan.")[:750], y)
        y = book.section("03", "How we stay in sync", "Weekly progress updates cover completed work, upcoming milestones, and any decisions we need from you. One shared project history keeps the work traceable.", y)
        book.text("NEXT STEP", 44, max(110, y), 10, color=PURPLE, bold=True)
        book.text("Review the direction with your ZanDop contact.", 44, max(86, y - 23), 13, bold=True)
        book.end()
    book.save()
    db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (document_id, lead["id"], kind, version, title, relative, now()))
    event(db, lead["id"], "Researcher" if kind == "brief" else "Client Success", "document.created", f"{kind} PDF version {version}")
    return {"id": document_id, "path": relative, "title": title, "kind": kind, "version": version}
