#!/usr/bin/env python3
"""Record the lifecycle tag policy creation flow in the web dashboard."""

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


async def safe_type(page, selector, text, delay=80, timeout=5000):
    """Type into element if found."""
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.click()
        await loc.press_sequentially(text, delay=delay)
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

        # Navigate to lifecycle policies
        await page.goto(f"{BASE_URL}/lifecycle/policies")
        await page.wait_for_load_state("networkidle")
        await natural_pause(2500, 3000)

        # Click "New Policy" button
        await safe_click(page, "button:has-text('New Policy')")
        await natural_pause(1000, 1500)

        # Wait for dialog
        try:
            await page.wait_for_selector(".dialog-overlay", state="visible", timeout=5000)
        except Exception:
            pass
        await natural_pause(500, 800)

        # Fill policy name
        await safe_type(page, "input[placeholder='e.g. dev-cleanup']", "demo-env-cleanup")
        await natural_pause(400, 600)

        # Fill description
        await safe_type(page, "input[placeholder='Optional description']", "Clean up demo environment resources")
        await natural_pause(500, 800)

        # --- Expand Resource Types section (starts collapsed) ---
        rt_header = page.locator(".section-header:has(.section-label:has-text('Resource Types'))").first
        try:
            await rt_header.click()
            await natural_pause(500, 700)
        except Exception:
            pass

        # Click resource type checkboxes
        for label in ["Lambda Function", "EC2 Instance"]:
            try:
                cb = page.locator(f".checkbox-item:has-text('{label}')").first
                await cb.click()
                await natural_pause(400, 500)
            except Exception:
                pass

        await natural_pause(500, 800)

        # Scroll dialog down a bit
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop += 150")
        except Exception:
            pass
        await natural_pause(400, 600)

        # --- Expand Tag Conditions section (starts collapsed) ---
        tc_header = page.locator(".section-header:has(.section-label:has-text('Tag Conditions'))").first
        try:
            await tc_header.click()
            await natural_pause(500, 700)
        except Exception:
            pass

        # Click "Add Condition" button
        await safe_click(page, "button:has-text('Add Condition')")
        await natural_pause(500, 700)

        # Fill tag key
        await safe_type(page, "input[placeholder='Tag key (e.g. Environment)']", "Environment")
        await natural_pause(400, 500)

        # Select "contains" operator
        try:
            await page.locator(".dynamic-row select").first.select_option("contains")
        except Exception:
            pass
        await natural_pause(400, 500)

        # Fill value
        await safe_type(page, "input[placeholder='Value']", "demo")
        await natural_pause(500, 800)

        # Wait for match preview to update
        await natural_pause(1500, 2000)

        # Scroll dialog to see lifecycle settings
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop += 200")
        except Exception:
            pass
        await natural_pause(500, 800)

        # Set TTL to 7 days
        try:
            ttl = page.locator("input[type='number'][min='1'][max='3650']").first
            await ttl.click()
            await ttl.fill("7")
            await natural_pause(400, 600)
        except Exception:
            pass

        # Scroll to dialog bottom
        try:
            await page.locator(".dialog-box").evaluate("el => el.scrollTop = el.scrollHeight")
        except Exception:
            pass
        await natural_pause(500, 800)

        # Submit
        await safe_click(page, "button:has-text('Create Policy')")
        await natural_pause(2500, 3000)

        # Wait for dialog to close
        try:
            await page.wait_for_selector(".dialog-overlay", state="hidden", timeout=10000)
        except Exception:
            try:
                await page.locator(".dialog-overlay").click(position={"x": 10, "y": 10})
            except Exception:
                pass
        await natural_pause(1500, 2000)

        # Scroll to top to see policy list
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await natural_pause(1000, 1500)

        # Try to expand policy to show matched resources
        if await safe_click(page, "button[title='Show matched resources']"):
            await natural_pause(1500, 2000)

        # Scroll to see matched resources
        await slow_scroll(page, 300, 4)
        await natural_pause(2000, 2500)

        # Final hold
        await natural_pause(3000, 3000)

        await context.close()
        await browser.close()

    print("Lifecycle tag recording complete.")


if __name__ == "__main__":
    asyncio.run(record())
