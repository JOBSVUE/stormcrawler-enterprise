"""
Playwright Render API (FastAPI)

- Default port: 8001 (so it doesn't conflict with extractor on 8000).
- GET  /health                 -> simple healthcheck
- POST /render                 -> returns fully rendered HTML + fetch metadata
- POST /render_and_extract     -> renders, then POSTs to extractor and returns extracted JSON
"""

import os
import time
import logging
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl, Field

from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    TimeoutError as PlaywrightTimeoutError,
)
import httpx

# Configuration
APP_PORT = int(os.getenv("PORT", "8001"))
HEADLESS = os.getenv("HEADLESS", "1") not in ("0", "false", "False")
BROWSER_CHOICE = os.getenv("BROWSER", "chromium")  # chromium | firefox | webkit
DEFAULT_TIMEOUT_MS = int(os.getenv("NAV_TIMEOUT_MS", "30000"))  # navigation timeout in ms

# Extractor URL for chaining
EXTRACTOR_URL = os.getenv("EXTRACTOR_URL", "http://extractor:8000/extract")

# Logging
logger = logging.getLogger("playwright_renderer")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI(title="Playwright Render API", version="1.0")

# Global Playwright/browser instances reused across requests
_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None


class RenderRequest(BaseModel):
    url: HttpUrl
    wait_for_selector: Optional[str] = None
    timeout_ms: Optional[int] = Field(None, ge=1000)  # ms
    user_agent: Optional[str] = None
    capture_resources: Optional[bool] = False  # placeholder for future use


class RenderResponse(BaseModel):
    url: HttpUrl
    html_content: str
    fetch_metadata: Dict[str, Any]
    timestamp_ms: int


@app.get("/health")
async def health():
    # Report unhealthy until browser is ready
    if _browser is None:
        raise HTTPException(status_code=503, detail="starting")
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    global _playwright, _browser
    logger.info("Starting Playwright...")
    _playwright = await async_playwright().start()
    browser_choice = (BROWSER_CHOICE or "chromium").lower()
    try:
        if browser_choice == "chromium":
            _browser = await _playwright.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        elif browser_choice == "firefox":
            _browser = await _playwright.firefox.launch(headless=HEADLESS)
        elif browser_choice == "webkit":
            _browser = await _playwright.webkit.launch(headless=HEADLESS)
        else:
            raise RuntimeError(f"Unsupported browser: {browser_choice}")
        logger.info("Browser started: %s (headless=%s)", browser_choice, HEADLESS)
    except Exception as exc:
        logger.exception("Failed to start Playwright browser")
        raise RuntimeError("Failed to start Playwright browser: " + str(exc)) from exc


@app.on_event("shutdown")
async def shutdown_event():
    global _browser, _playwright
    logger.info("Shutting down browser/playwright...")
    try:
        if _browser:
            await _browser.close()
    finally:
        if _playwright:
            await _playwright.stop()


async def _render_page(url: str, wait_for_selector: Optional[str], timeout_ms: int, user_agent: Optional[str]) -> RenderResponse:
    global _browser
    if not _browser:
        raise HTTPException(status_code=500, detail="Browser not initialized")

    timeout = timeout_ms or DEFAULT_TIMEOUT_MS
    context_args = {}
    if user_agent:
        context_args["user_agent"] = user_agent

    context = await _browser.new_context(**context_args)
    page = await context.new_page()

    try:
        response = await page.goto(url, wait_until="networkidle", timeout=timeout)
        if wait_for_selector:
            try:
                await page.wait_for_selector(wait_for_selector, timeout=timeout)
            except PlaywrightTimeoutError:
                logger.info("wait_for_selector '%s' not found within timeout for %s", wait_for_selector, url)

        html = await page.content()

        status = None
        headers = {}
        content_type = None
        if response:
            try:
                status = response.status
                headers = dict(response.headers)
                content_type = headers.get("content-type")
            except Exception:
                logger.debug("Unable to read response metadata for %s", url)

        fetch_metadata = {
            "status": status,
            "headers": headers,
            "content_type": content_type,
        }
        timestamp_ms = int(time.time() * 1000)

        return RenderResponse(
            url=url,
            html_content=html,
            fetch_metadata=fetch_metadata,
            timestamp_ms=timestamp_ms,
        )
    finally:
        try:
            await context.close()
        except Exception:
            pass


@app.post("/render", response_model=RenderResponse)
async def render_endpoint(payload: RenderRequest):
    try:
        rendered = await _render_page(str(payload.url), payload.wait_for_selector, payload.timeout_ms or DEFAULT_TIMEOUT_MS, payload.user_agent)
        return JSONResponse(status_code=200, content=rendered.dict())
    except PlaywrightTimeoutError:
        logger.exception("Navigation/render timed out for %s", payload.url)
        raise HTTPException(status_code=504, detail="Navigation/render timed out")
    except Exception as exc:
        logger.exception("Rendering failed for %s", payload.url)
        raise HTTPException(status_code=500, detail=f"Rendering failed: {exc}")


@app.post("/render_and_extract")
async def render_and_extract_endpoint(payload: RenderRequest):
    """
    Render the page, then POST rendered HTML to extractor and return extractor's response as-is.
    """
    try:
        rendered = await _render_page(str(payload.url), payload.wait_for_selector, payload.timeout_ms or DEFAULT_TIMEOUT_MS, payload.user_agent)
    except PlaywrightTimeoutError:
        logger.exception("Navigation/render timed out for %s", payload.url)
        raise HTTPException(status_code=504, detail="Navigation/render timed out")
    except Exception as exc:
        logger.exception("Rendering failed for %s", payload.url)
        raise HTTPException(status_code=500, detail=f"Rendering failed: {exc}")

    body = {
        "url": rendered.url,
        "html_content": rendered.html_content,
        "fetch_metadata": rendered.fetch_metadata,
        # Optional: passthrough metadata/company_id if you add them to request later
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(EXTRACTOR_URL, json=body)
            if resp.status_code == 200:
                return JSONResponse(status_code=200, content=resp.json())
            elif resp.status_code == 204:
                return JSONResponse(status_code=204, content=None)
            else:
                logger.warning("Extractor returned status %s for %s: %s", resp.status_code, payload.url, resp.text[:2000])
                raise HTTPException(status_code=502, detail=f"Extractor error: HTTP {resp.status_code}")
    except httpx.TimeoutException:
        logger.exception("Extractor call timed out for %s", payload.url)
        raise HTTPException(status_code=504, detail="Extractor call timed out")
    except Exception as exc:
        logger.exception("Extractor call failed for %s", payload.url)
        raise HTTPException(status_code=502, detail=f"Extractor call failed: {exc}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=APP_PORT, log_level="info")
