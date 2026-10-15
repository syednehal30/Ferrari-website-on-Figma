"""Exercise the authenticated real-workspace UI without connecting or sending email."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
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
            server = subprocess.Popen([sys.executable, "scripts/local_demo.py", "--serve", "--workspace", "--no-browser"], cwd=root, env=config, stdout=log, stderr=log)
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
                    page.get_by_role("heading", name="Your agency, in motion.").wait_for()
                    assert page.request.get(address + "/api/state").json()["mode"] == "paused"
                    page.goto(address + "/#local-setup")
                    page.get_by_role("heading", name="Set up your local agency.").wait_for()
                    page.get_by_role("button", name="Enable automatic replies").click()
                    page.get_by_text("Test your Gmail connection successfully before enabling automatic replies.", exact=True).wait_for()
                    page.goto(address + "/#overview")
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
                    for route in ("inbox", "local-setup"):
                        page.goto(address + "/#" + route)
                        page.set_viewport_size({"width": 390, "height": 844})
                        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), route
                    assert not errors, errors
                    browser.close()
                second = subprocess.run([sys.executable, "scripts/local_demo.py", "--serve", "--workspace", "--no-browser"], cwd=root, env=config, capture_output=True, text=True, timeout=10)
                assert second.returncode == 0 and "already running" in second.stdout
                print("PASS: authenticated local launch, Gmail activation gate, inbox, questionnaire queue, $500 quote + PDF, explicit approval, revision invalidation, paused sends, mobile screens, and single-instance protection.")
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
