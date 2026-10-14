"""Run against an isolated demo server. No external effects are enabled."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "test-results"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        config = {**os.environ, "ZANDOP_DATA_DIR": temporary, "ZANDOP_LIVE_MODE": "false", "ZANDOP_OPERATOR_TOKEN": "", "ZANDOP_SEED_DEMO": "true"}
        with (output / "browser-server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "zandop.main:app", "--host", "127.0.0.1", "--port", "8001"], cwd=root, env=config, stdout=log, stderr=log)
            try:
                for _ in range(50):
                    try:
                        if httpx.get("http://127.0.0.1:8001/api/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise AssertionError("Isolated browser-test server did not become healthy")
                with sync_playwright() as p:
                    browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_EXECUTABLE") or shutil.which("chromium"), headless=True, args=["--no-sandbox"])
                    page = browser.new_page(viewport={"width": 1440, "height": 1080}, reduced_motion="reduce")
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto("http://127.0.0.1:8001", wait_until="networkidle")
                    page.get_by_role("heading", name="Your agency, in motion.").wait_for()
                    page.screenshot(path=str(output / "dashboard-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.screenshot(path=str(output / "dashboard-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1080})
                    for route, title in [("workflow", "Eleven specialists. One team."), ("crm", "Good opportunities start here."), ("documents", "Make the first impression count."), ("approvals", "Your judgment. Their next step."), ("integrations", "The right tools, working together."), ("activity", "Nothing falls through the cracks.")]:
                        page.goto("http://127.0.0.1:8001/#" + route)
                        page.get_by_role("heading", name=title).wait_for()
                        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), route
                    page.goto("http://127.0.0.1:8001/#crm")
                    page.get_by_role("searchbox").fill("Forma")
                    assert page.locator("tbody tr").count() == 1
                    page.locator("tbody tr").click()
                    page.get_by_role("dialog").wait_for()
                    page.get_by_role("button", name="Simulate booking").click()
                    page.get_by_role("button", name="Add call notes").wait_for()
                    page.get_by_role("button", name="Add call notes").click()
                    page.locator('textarea[name="notes"]').fill("Client confirmed the mobile catalog direction and the two-product concept. Use a warm, considered voice.")
                    page.get_by_role("button", name="Save call notes").click()
                    page.wait_for_selector(".modal", state="detached")
                    page.goto("http://127.0.0.1:8001/#approvals")
                    page.get_by_role("button", name="Review request").first.click()
                    page.get_by_role("button", name="Approve simulation").click()
                    assert page.get_by_text("Review the request and select the approval checkbox first.").is_visible()
                    page.locator("#approval-confirm").check()
                    page.get_by_role("button", name="Approve simulation").click()
                    page.wait_for_selector(".modal", state="detached")
                    page.goto("http://127.0.0.1:8001/#overview")
                    page.get_by_role("button", name="Run next cycle").click()
                    page.get_by_text("Cycle complete.", exact=False).wait_for()
                    page.get_by_role("button", name="Add a lead").click()
                    page.locator('input[name="name"]').fill("Browser Test Co")
                    page.locator('input[name="email"]').fill("browser-test@example.com")
                    page.get_by_role("button", name="Add lead", exact=True).click()
                    page.wait_for_selector(".modal", state="detached")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                    assert page.locator(".sidebar").bounding_box()["x"] < 0
                    page.get_by_role("button", name="Toggle navigation").click()
                    assert page.locator(".sidebar").bounding_box()["x"] == 0
                    page.get_by_role("link", name="Client documents").click()
                    page.get_by_role("heading", name="Make the first impression count.").wait_for()
                    assert page.locator(".sidebar").bounding_box()["x"] < 0
                    assert not errors, errors
                    browser.close()
                response = httpx.get("http://127.0.0.1:8001/api/state")
                state = response.json()
                doc = state["documents"][0]
                pdf = httpx.get(f"http://127.0.0.1:8001/api/documents/{doc['id']}/download")
                assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
                diagram = httpx.get("http://127.0.0.1:8001/workflow.svg")
                assert diagram.status_code == 200 and "Referral" in diagram.text
                assert any(lead["name"] == "Browser Test Co" for lead in state["leads"])
                print("PASS: 7 routes, desktop/mobile layouts, search, booking, call notes, approval guard + decision, worker cycle, lead creation, PDF and diagram downloads; no JavaScript errors.")
            finally:
                server.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    main()
