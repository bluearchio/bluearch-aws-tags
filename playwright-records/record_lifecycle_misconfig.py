#!/usr/bin/env python3
"""Record the misconfig policy creation and scan flow in the web dashboard."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from helpers import natural_pause, slow_scroll

BASE_URL = os.environ.get("DEMO_URL", "http://localhost:8095")


async def safe_click(page, selector, timeout=5000):
    """Click element if found, return True if clicked."""
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click()
        return True
    except Exception:
        return False


async def record():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            record_video_dir="./playwright-records/videos/",
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        # Navigate to misconfig page
        await page.goto(f"{BASE_URL}/lifecycle/misconfig")
        await page.wait_for_load_state("networkidle")
        await natural_pause(2000, 2500)

        # --- Create a new misconfig policy ---
        await safe_click(page, "button:has-text('New Policy')")
        await natural_pause(1000, 1500)

        # Wait for dialog
        try:
            await page.wait_for_selector(".dialog-overlay", state="visible", timeout=5000)
        except Exception:
            pass
        await natural_pause(500, 800)

        # Fill policy name
        name_input = page.locator("input[placeholder='e.g. ec2-security-checks']").first
        try:
            await name_input.wait_for(state="visible", timeout=5000)
            await name_input.click()
            await name_input.press_sequentially("AWS Best Practices Baseline", delay=60)
        except Exception:
            pass
        await natural_pause(400, 600)

        # Fill description
        desc_input = page.locator("input[placeholder='Optional description']").first
        try:
            await desc_input.click()
            await desc_input.press_sequentially("Deprecated runtimes, old instance types, unencrypted volumes", delay=50)
        except Exception:
            pass
        await natural_pause(500, 800)

        # --- Select resource types: EC2 Instance, Lambda Function, EBS Volume ---
        for label in ["EC2 Instance", "Lambda Function", "EBS Volume"]:
            try:
                cb = page.locator(f".checkbox-item:has-text('{label}')").first
                await cb.click()
                await natural_pause(400, 500)
            except Exception:
                pass

        # Wait for catalog to load
        await natural_pause(2000, 2500)

        # Scroll dialog to see misconfigurations section
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop += 250")
        except Exception:
            pass
        await natural_pause(800, 1000)

        # Click "Select All" button for misconfigurations
        await safe_click(page, "button:has-text('Select All')")
        await natural_pause(1000, 1500)

        # Scroll to see the selected misconfigs
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop += 200")
        except Exception:
            pass
        await natural_pause(1000, 1500)

        # Scroll to dialog bottom to see submit button
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop = el.scrollHeight")
        except Exception:
            pass
        await natural_pause(500, 800)

        # Submit the policy
        await safe_click(page, "button:has-text('Create Policy')")
        await natural_pause(2000, 2500)

        # Wait for dialog to close
        try:
            await page.wait_for_selector(".dialog-overlay", state="hidden", timeout=10000)
        except Exception:
            pass
        await natural_pause(1500, 2000)

        # --- Run misconfig evaluation via API (not the Scan Resources button) ---
        # This evaluates rules against existing DB resources (mock data)
        await page.evaluate("""
            async () => {
                await fetch('/api/v1/misconfig/scan', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: '{}'
                });
            }
        """)
        await natural_pause(2000, 2500)

        # Reload page to show findings
        await page.reload()
        await page.wait_for_load_state("networkidle")
        await natural_pause(2000, 2500)

        # Scroll to see summary cards and findings
        await slow_scroll(page, 200, 3)
        await natural_pause(1500, 2000)

        # Scroll through findings table
        await slow_scroll(page, 200, 3)
        await natural_pause(1500, 2000)

        # Scroll back up to see full dashboard
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await natural_pause(2000, 2500)

        # Hold final view
        await natural_pause(3000, 3000)

        await context.close()
        await browser.close()

    print("Misconfig recording complete. Video saved to ./videos/")


if __name__ == "__main__":
    asyncio.run(record())
