"""Shared async helpers for human-like browser interaction in Playwright recordings."""

import asyncio
import random


async def human_type(page, selector: str, text: str, min_delay: int = 50, max_delay: int = 150):
    """Type text character-by-character with random delays to simulate human typing."""
    element = page.locator(selector)
    await element.click()
    for char in text:
        await element.press_sequentially(char, delay=random.randint(min_delay, max_delay))


async def human_click(page, selector: str, before_ms: int = 300, after_ms: int = 500):
    """Click an element with natural before/after delays."""
    await asyncio.sleep(before_ms / 1000)
    await page.locator(selector).click()
    await asyncio.sleep(after_ms / 1000)


async def human_move_to(page, selector: str):
    """Hover over an element with a small pause."""
    await page.locator(selector).hover()
    await asyncio.sleep(random.randint(200, 400) / 1000)


async def slow_scroll(page, pixels: int, steps: int = 5):
    """Scroll incrementally with pauses between steps."""
    step_size = pixels // steps
    for _ in range(steps):
        await page.mouse.wheel(0, step_size)
        await asyncio.sleep(random.randint(100, 250) / 1000)


async def natural_pause(min_ms: int = 500, max_ms: int = 1500):
    """Random pause to simulate human thinking time."""
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def wait_visible(page, selector: str, timeout: int = 10000):
    """Wait for an element to be visible on the page."""
    await page.locator(selector).wait_for(state="visible", timeout=timeout)
