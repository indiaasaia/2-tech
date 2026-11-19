import sys
import time
from playwright.sync_api import sync_playwright

url = "https://de.linkedin.com/jobs/view/robotics-software-engineer-data-ai-%E2%80%93-working-student-m-f-d-at-driveblocks-4476097364?utm_source=workingstudentjobs.de&utm_medium=job_board&utm_campaign=organic"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, timeout=45000)
    page.wait_for_timeout(3000)
    
    # Cookie consent
    for btn in page.locator("button").all():
        text = btn.inner_text().strip()
        if any(w in text.lower() for w in ['accept', 'zulassen', 'einverstanden']):
            btn.click()
            break
    page.wait_for_timeout(2000)
    
    print("Page URL after cookies:", page.url)
    
    # Print all buttons
    for btn in page.locator("button, a").all():
        text = btn.inner_text().strip().replace("\n", " ")
        if any(w in text.lower() for w in ['apply', 'bewerb', 'easy', 'anmelden', 'sign in', 'weiter']):
            print("Action element:", btn.evaluate("el => ({tag: el.tagName, text: el.innerText, href: el.getAttribute('href'), class: el.className})"))
            
    browser.close()
