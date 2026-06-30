#!/usr/bin/env python3
"""Record the AI chat assistant flow in the web dashboard."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from playwright.async_api import async_playwright
from helpers import natural_pause

BASE_URL = os.environ.get("DEMO_URL", "http://localhost:8095")


async def scroll_chat_bottom(page):
    """Scroll the .messages container to the bottom."""
    await page.evaluate("""
        () => {
            const el = document.querySelector('.messages');
            if (el) el.scrollTop = el.scrollHeight;
        }
    """)


async def wait_for_response(page, expected_msg_count, timeout_ms=90000, poll_ms=1000):
    """Wait for AI streaming response to complete.

    Uses message count + model-badge to detect completion reliably.
    The .model-badge only renders on the last assistant message when !isStreaming.
    We verify message count to avoid catching a stale badge from a previous response.
    """
    # Give streaming time to start
    await asyncio.sleep(2)
    await scroll_chat_bottom(page)

    elapsed = 2000
    while elapsed < timeout_ms:
        done = await page.evaluate("""
            (expectedCount) => {
                const msgs = document.querySelectorAll('.message');
                const badge = document.querySelector('.model-badge');
                return msgs.length >= expectedCount && !!badge;
            }
        """, expected_msg_count)
        if done:
            break
        await scroll_chat_bottom(page)
        await asyncio.sleep(poll_ms / 1000)
        elapsed += poll_ms


async def record():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            record_video_dir="./playwright-records/videos/",
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720},
        )
        page = await context.new_page()

        # Navigate to chat
        await page.goto(f"{BASE_URL}/chat")
        await page.wait_for_load_state("networkidle")
        await natural_pause(1500, 2000)

        chat_input = page.locator("textarea.chat-input")
        await chat_input.wait_for(state="visible", timeout=10000)
        await natural_pause(500, 800)

        send_btn = page.locator(".send-btn")

        # --- First question ---
        await chat_input.click()
        await chat_input.press_sequentially(
            "What Lambda functions are using deprecated runtimes?",
            delay=55,
        )
        await natural_pause(300, 500)
        await send_btn.click()

        # Expect: 1 user msg + 1 assistant msg = 2 messages
        await wait_for_response(page, expected_msg_count=2)
        await scroll_chat_bottom(page)
        await natural_pause(2000, 2500)

        # --- Second question ---
        await chat_input.click()
        await chat_input.press_sequentially(
            "Which should I update first?",
            delay=55,
        )
        await natural_pause(300, 500)
        await send_btn.click()

        # Expect: 2 user msgs + 2 assistant msgs = 4 messages
        await wait_for_response(page, expected_msg_count=4)
        await scroll_chat_bottom(page)
        await natural_pause(2000, 2500)

        # --- Third question ---
        await chat_input.click()
        await chat_input.press_sequentially(
            "Can you fix them for me?",
            delay=55,
        )
        await natural_pause(300, 500)
        await send_btn.click()

        # Expect: 3 user msgs + 3 assistant msgs = 6 messages
        await wait_for_response(page, expected_msg_count=6)
        await scroll_chat_bottom(page)
        await natural_pause(3000, 3500)

        await context.close()
        await browser.close()

    print("AI chat recording complete. Video saved to ./videos/")


if __name__ == "__main__":
    asyncio.run(record())
