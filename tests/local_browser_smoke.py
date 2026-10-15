"""Exercise the authenticated real-workspace UI without connecting or sending email."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("launcher", root / "scripts/local_demo.py")
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    with tempfile.TemporaryDirectory(prefix="zandop local browser ") as temporary:
        directory = Path(temporary)
        config = launcher.workspace_environment(shutil.which("chromium"), temporary)
        for key in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "GMAIL_LABEL"):
            config.pop(key, None)
        with (directory / "server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "scripts/local_demo.py", "--serve", "--no-browser"], cwd=root, env=config, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if (directory / "Open ZanDop.html").is_file():
                        break
                    if server.poll() is not None:
                        raise AssertionError((directory / "server.log").read_text())
                    time.sleep(0.1)
                else:
                    raise AssertionError("Workspace did not become ready")
                address = json.loads((directory / ".instance.json").read_text())["address"]
                self_login = re.search(r'href="([^"]+)"', (directory / "Open ZanDop.html").read_text())[1]
                assert httpx.get(address + "/api/state").status_code == 401
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=shutil.which("chromium"), args=["--no-sandbox"])
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(self_login, wait_until="networkidle")
                    page.get_by_role("heading", name="Set up your local agency.").wait_for()
                    initial = page.request.get(address + "/api/state").json()
                    assert initial["mode"] == "paused" and initial["leads"] == []
                    assert page.url.endswith("#local-setup")
                    assert page.locator('[name="email"]').is_enabled()
                    assert page.locator('#mode-pill').inner_text() == 'Real workspace · setup needed'
                    assert page.locator('[name="password"]').is_enabled()
                    page.get_by_role("button", name="Enable automatic replies").click()
                    page.get_by_text("Test your Gmail connection successfully before enabling automatic replies.", exact=True).wait_for()
                    page.goto(address + "/#overview")
                    page.get_by_text("Your real workspace is open. Connect Gmail to begin.", exact=True).wait_for()
                    assert page.get_by_text("Demo proposal value", exact=True).count() == 0
                    page.get_by_text("Accepted scope value", exact=True).wait_for()
                    page.get_by_role("button", name="Add a lead").click()
                    page.locator('[name="name"]').fill("Local Browser Client")
                    page.locator('[name="email"]').fill("local-browser@example.com")
                    page.locator('[name="client_contact"]').check()
                    page.get_by_role("button", name="Add lead", exact=True).click()
                    page.wait_for_selector(".modal", state="detached")
                    page.goto(address + "/#inbox")
                    page.get_by_role("heading", name="Your client inbox.").wait_for()
                    page.locator('tr[data-action="lead"]').first.click()
                    page.get_by_role("button", name="Edit quote · $500+").click()
                    page.locator('[name="price"]').fill("500")
                    page.locator('[name="scope"]').fill("Three responsive pages with a contact form, client-supplied copy, and a setup handoff.")
                    page.get_by_role("button", name="Prepare quote for approval").click()
                    page.wait_for_selector(".modal", state="detached")
                    page.goto(address + "/#approvals")
                    page.get_by_role("button", name="Review request").first.click()
                    pdf_url = page.get_by_role("link", name="Review attached PDF").get_attribute("href")
                    pdf = page.request.get(address + pdf_url)
                    assert pdf.status == 200 and pdf.body().startswith(b"%PDF-")
                    page.locator("#approval-confirm").check()
                    page.get_by_role("button", name="Approve action", exact=True).click()
                    page.wait_for_selector(".modal", state="detached")
                    state = page.request.get(address + "/api/state").json()
                    assert len(state["leads"]) == 1 and len(state["approvals"]) == 1
                    assert state["approvals"][0]["status"] == "approved"
                    assert all(action["status"] == "pending" for action in state["outbox"])
                    lead_id = state["leads"][0]["id"]
                    detail = page.request.get(address + "/api/leads/" + lead_id).json()
                    assert not detail["messages"], "Paused workspace must not send any real messages"
                    page.goto(address + "/#inbox")
                    page.locator('tr[data-action="lead"]').first.click()
                    page.get_by_role("button", name="Edit quote · $500+").click()
                    page.locator('[name="price"]').fill("650")
                    page.get_by_role("button", name="Prepare quote for approval").click()
                    page.wait_for_selector(".modal", state="detached")
                    state = page.request.get(address + "/api/state").json()
                    assert [a["status"] for a in state["approvals"]] == ["pending", "superseded"]
                    page.goto(address + "/#growth")
                    page.get_by_role("heading", name="Find your next two clients.").wait_for()
                    page.get_by_role("heading", name="What is ready, and what is missing").wait_for()
                    page.get_by_text("No prospects or directory feeds yet. Paste business website URLs below or import your leads.", exact=True).wait_for()
                    page.clock.install()
                    page.locator('[name="market"]').fill("Independent furniture stores in Manchester")
                    page.locator('[name="daily_limit"]').fill("8")
                    page.clock.fast_forward(31000)
                    assert page.locator('[name="market"]').input_value() == "Independent furniture stores in Manchester", "Automatic refresh must not erase unsaved setup inputs"
                    assert page.locator('[name="daily_limit"]').input_value() == "8"
                    page.get_by_role("button", name="Save targeting").click()
                    page.wait_for_function("state.growth.daily_limit === 8 && state.growth.market === 'Independent furniture stores in Manchester'")
                    assert "Independent%20furniture" in page.get_by_role("link", name="Google Maps").get_attribute("href")
                    page.get_by_role("button", name="Enable personal Gmail outreach").click()
                    page.get_by_text("Connect and test your Gmail account in Local setup first.", exact=True).wait_for()
                    prospect = page.request.post(address + "/api/leads", data={"name": "Browser Prospect", "email": "prospect@example.com", "service": "website"}).json()
                    draft = {"subject": "Your mobile experience", "body": "The page is missing a mobile viewport declaration. Could we help improve how people find your services on a phone? ZanDop"}
                    with sqlite3.connect(directory / "zandop.sqlite3") as db:
                        db.execute("UPDATE leads SET stage=3,details=? WHERE id=?", (json.dumps({"outreach_candidate": True, "outreach_draft": draft, "research": {"flaw": "The page is missing a mobile viewport declaration."}}), prospect["id"]))
                    page.reload(wait_until="networkidle")
                    page.get_by_role("button", name="Review first email", exact=True).click()
                    page.get_by_text(draft["body"], exact=True).wait_for()
                    page.locator('.modal input[type="checkbox"]').check()
                    page.get_by_role("button", name="Allow this first email").click()
                    page.wait_for_selector(".modal", state="detached")
                    detail = page.request.get(address + "/api/leads/" + prospect["id"]).json()
                    assert detail["lead"]["details"]["outreach_review_hash"] == detail["outreach_hash"]
                    assert not detail["messages"], "Review must not bypass paused automation"
                    page.screenshot(path="/tmp/zandop-growth-desktop.png", full_page=True)
                    for route in ("inbox", "local-setup", "growth", "integrations"):
                        page.goto(address + "/#" + route)
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), route
                    assert not errors, errors
                    browser.close()
                second = subprocess.run([sys.executable, "scripts/local_demo.py", "--serve", "--workspace", "--no-browser"], cwd=root, env=config, capture_output=True, text=True, timeout=10)
                assert second.returncode == 0 and "already running" in second.stdout
                print("PASS: authenticated local launch, Gmail activation gate, inbox, questionnaire, $500 quote + PDF, approval, revision invalidation, paused sends, growth targeting, exact outreach review, mobile screens, and single-instance protection.")
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
