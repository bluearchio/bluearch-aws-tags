#!/usr/bin/env python3
"""Record the cost analysis view in the web dashboard."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from helpers import human_click, natural_pause, slow_scroll

BASE_URL = os.environ.get("DEMO_URL", "http://localhost:8095")


async def record():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            record_video_dir="./playwright-records/videos/",
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        # Navigate to cost page
        await page.goto(f"{BASE_URL}/cost")
        await page.wait_for_load_state("networkidle")
        await natural_pause(2000, 2500)

        # Click through period buttons
        period_buttons = page.locator(".period-btn")
        count = await period_buttons.count()
        if count > 0:
            # Click each period button with pauses
            for i in range(min(count, 4)):
                btn = period_buttons.nth(i)
                btn_text = await btn.text_content()
                if btn_text and any(x in btn_text for x in ["7", "30", "90", "180"]):
                    await btn.click()
                    await natural_pause(1500, 2000)

        # Scroll to see cost breakdown charts
        await slow_scroll(page, 300, 4)
        await natural_pause(1500, 2000)

        # Click on a chart card if available (service breakdown)
        chart_card = page.locator(".chart-card.clickable-chart").first
        if await chart_card.count() > 0:
            await chart_card.click()
            await natural_pause(1500, 2000)

        # Scroll to see drilldown table
        await slow_scroll(page, 300, 4)
        await natural_pause(1500, 2000)

        # Scroll back to top
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await natural_pause(1500, 2000)

        # Try clicking the "Daily" tab
        daily_tab = page.locator(".period-btn:has-text('Daily')")
        if await daily_tab.count() > 0:
            await daily_tab.click()
            await natural_pause(1500, 2000)
            await slow_scroll(page, 200, 3)
            await natural_pause(1000, 1500)

        # Back to Overview
        overview_tab = page.locator(".period-btn:has-text('Overview')")
        if await overview_tab.count() > 0:
            await overview_tab.click()
            await natural_pause(1500, 2000)

        # Scroll back up
        await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        await natural_pause(1500, 2000)

        # Hold final view
        await natural_pause(3000, 3000)

        await context.close()
        await browser.close()

    print("Cost recording complete. Video saved to ./videos/")


if __name__ == "__main__":
    asyncio.run(record())
