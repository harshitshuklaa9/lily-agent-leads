import os
import httpx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from agents.base_agent import BaseAgent


class DiscoveryAgent(BaseAgent):
    model_key = "discovery"
    """
    Finds companies per event using a three-tier fallback cascade:
      1. Playwright scrape — navigates exhibitor page, waits for JS render,
         scrolls to load dynamic content, intercepts API responses
      2. Serper search: "[event] exhibitors site:linkedin.com OR site:businesswire.com"
      3. Serper search: "[event] 2025 companies attending graphics signage"
    """

    def run(self, events: list[dict]) -> list[dict]:
        all_companies = []
        max_per_event = self.config["discovery"]["max_companies_per_event"]

        for event in events:
            self.logger.info("DiscoveryAgent: processing '%s'", event["name"])
            companies, confidence = self._discover(event, max_per_event)

            if not companies:
                self.logger.warning("DiscoveryAgent: no companies found for '%s'", event["name"])
                continue

            for company in companies:
                company["event_source"] = event["name"]
                company["discovery_confidence"] = confidence

            self.logger.info(
                "DiscoveryAgent: %d companies for '%s' (%s)",
                len(companies), event["name"], confidence
            )
            all_companies.extend(companies)

        return all_companies

    # ------------------------------------------------------------------
    # Fallback cascade
    # ------------------------------------------------------------------

    def _discover(self, event: dict, max_results: int) -> tuple[list[dict], str]:
        import re as _re

        # Try 1: Playwright on the initial exhibitor_page URL
        if event.get("exhibitor_page"):
            companies = self._scrape_exhibitors(event["exhibitor_page"], event["name"])
            if companies:
                return companies[:max_results], "confirmed_exhibitor"

        # Try 2: Find and scrape a MapYourShow public exhibitor gallery
        # MapYourShow is used by ISA, PRINTING United, and many other major shows
        event_base = _re.sub(r'\s+20\d{2}\s*$', '', event["name"]).strip()
        mys_url = self._find_mapyourshow_url(event["name"], event_base)
        if mys_url:
            self.logger.info("DiscoveryAgent: found MapYourShow URL → %s", mys_url)
            companies = self._scrape_exhibitors(mys_url, event["name"])
            if companies:
                return companies[:max_results], "confirmed_exhibitor"

        # Build ICP context for Serper fallback queries
        industry = self.config.get("research", {}).get("industry", {})
        verticals = industry.get("verticals", [])
        buyer_kws = industry.get("buyer_keywords", [])
        icp_terms = " OR ".join(f'"{v}"' for v in (verticals[:3] + buyer_kws[:2]))

        # Extract show domain for site: targeting
        show_domain = ""
        url = event.get("url", "")
        m = _re.search(r"https?://(?:www\.)?([^/]+)", url)
        if m:
            show_domain = m.group(1)

        # Build fallback queries: show site search first, then ICP-targeted, then generic
        queries = []
        if show_domain:
            queries.append(f'site:{show_domain} exhibitors')
        queries.append(f'"{event["name"]}" exhibitors {icp_terms}')
        for query_template in self.config["discovery"].get("serper_fallback_queries", []):
            queries.append(
                query_template
                .replace("{event}", event["name"])
                .replace("{icp_verticals}", " OR ".join(f'"{v}"' for v in verticals[:3]))
                .replace("{icp_buyers}", " OR ".join(f'"{k}"' for k in buyer_kws[:2]))
            )

        for query in queries:
            companies = self._serper_search(query, event["name"])
            if companies:
                return companies[:max_results], "inferred_attendee"

        return [], "low_confidence"

    def _find_mapyourshow_url(self, event_name: str, event_base: str) -> str | None:
        """
        Searches for the MapYourShow exhibitor gallery URL for this event.
        MapYourShow is the most common public exhibitor directory platform.
        Returns the gallery URL if found, None otherwise.
        """
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            return None

        # Note: site:mapyourshow.com returns 0 results — use keyword approach instead
        query = f'{event_base} mapyourshow exhibitors'
        self.logger.info("DiscoveryAgent: searching for MapYourShow URL → %s", query)
        try:
            response = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 5},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as e:
            self.logger.warning("DiscoveryAgent: MapYourShow search failed — %s", e)
            return None

        for item in results.get("organic", []):
            link = item.get("link", "")
            # Prefer the exhibitor gallery page specifically
            if "mapyourshow.com" in link and "exhibitor-gallery" in link:
                return link
        # Fallback: any mapyourshow.com page for this event
        for item in results.get("organic", []):
            link = item.get("link", "")
            if "mapyourshow.com" in link:
                # Construct exhibitor gallery URL from the base
                import re as _re
                base = _re.sub(r'(/8_0/).*', r'/8_0/explore/exhibitor-gallery.cfm?featured=false', link)
                if base != link:
                    return base
                return link
        return None

    # ------------------------------------------------------------------
    # Try 1: Playwright with JS-rendering support
    # ------------------------------------------------------------------

    # Login wall signals — if any appear in page text, the page is gated
    _LOGIN_SIGNALS = [
        "sign in to view", "log in to view", "login to see", "register to view",
        "create an account", "members only", "please log in", "please sign in",
        "you must be logged in", "login required", "sign up to access",
    ]

    def _scrape_exhibitors(self, url: str, event_name: str) -> list[dict]:
        self.logger.info("DiscoveryAgent: Playwright scrape → %s", url)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    # Disable automation flags that trigger bot detection
                    java_script_enabled=True,
                )

                # Intercept ALL JSON responses — not just URL-keyword matched ones
                intercepted_json = []

                def handle_response(response):
                    try:
                        ct = response.headers.get("content-type", "")
                        if "json" in ct:
                            data = response.json()
                            # Only keep if it looks like a list of companies (array or has list keys)
                            if isinstance(data, list) and len(data) > 2:
                                intercepted_json.append(data)
                            elif isinstance(data, dict):
                                for v in data.values():
                                    if isinstance(v, list) and len(v) > 2:
                                        intercepted_json.append(data)
                                        break
                    except Exception:
                        pass

                page = context.new_page()
                page.on("response", handle_response)

                # Dismiss cookie banners before they block content
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)

                page.goto(url, timeout=20000, wait_until="domcontentloaded")

                # Fast login-wall detection — bail immediately, don't waste 25s
                try:
                    page_text = page.inner_text("body").lower()
                    for signal in self._LOGIN_SIGNALS:
                        if signal in page_text:
                            self.logger.info(
                                "DiscoveryAgent: login wall detected on %s — skipping to Serper", url
                            )
                            browser.close()
                            return []
                except Exception:
                    pass

                # Try to dismiss cookie/consent banners
                for selector in ["button:has-text('Accept')", "button:has-text('Accept All')",
                                  "button:has-text('OK')", "[id*='cookie'] button",
                                  "[class*='consent'] button"]:
                    try:
                        page.click(selector, timeout=1500)
                        break
                    except Exception:
                        pass

                # Wait for network to settle
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except PlaywrightTimeout:
                    pass

                # Scroll and click "Load More" to get paginated exhibitor results
                for attempt in range(8):
                    page.evaluate("window.scrollBy(0, window.innerHeight)")
                    try:
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
                    # Click "Load More" / "Show More" buttons if present
                    for btn_text in ["Load More Results", "Load More", "Show More", "View More", "See More", "See All Results"]:
                        try:
                            btn = page.locator(f"button:has-text('{btn_text}'), a:has-text('{btn_text}')").first
                            if btn.is_visible(timeout=500):
                                btn.click()
                                page.wait_for_timeout(1000)
                                break
                        except Exception:
                            pass

                # Prefer page text over raw HTML — cleaner for LLM extraction
                try:
                    page_text = page.inner_text("body")
                except Exception:
                    page_text = ""
                html = page.content()
                browser.close()

            # Try intercepted API data first — much cleaner than HTML parsing
            if intercepted_json:
                companies = self._extract_from_json(intercepted_json, event_name)
                if companies:
                    self.logger.info("DiscoveryAgent: extracted %d companies from intercepted API", len(companies))
                    return companies

            # Try text extraction first (cleaner than HTML for MapYourShow-style pages)
            if page_text and len(page_text) > 200:
                companies = self._extract_companies_from_text(page_text, event_name)
                if companies:
                    return companies

            return self._extract_companies_from_html(html, event_name)

        except PlaywrightTimeout:
            self.logger.warning("DiscoveryAgent: Playwright timeout on %s", url)
            return []
        except Exception as e:
            self.logger.warning("DiscoveryAgent: Playwright failed — %s", e)
            return []

    def _extract_from_json(self, json_list: list, event_name: str) -> list[dict]:
        import json
        raw = json.dumps(json_list[:5])[:30000]

        system_prompt = "You are a data extraction assistant. You return JSON only."
        user_prompt = f"""
Extract exhibiting company names from this API response data captured from the {event_name} exhibitor page.

CRITICAL RULES — violation means wrong output:
- ONLY include companies whose exact name appears verbatim in the data below
- DO NOT infer, guess, complete, or add any company name not literally present in the text
- If a company name is ambiguous or partial, skip it
- Return empty list if no clear company names are found

Return JSON:
{{
  "companies": [
    {{"name": "Exact Company Name As It Appears", "website": "https://... or null", "description": "one line or null"}}
  ]
}}

Data:
{raw}
"""
        try:
            result = self.call_llm(system_prompt, user_prompt)
            companies = result.get("companies", [])
            return self._verbatim_filter(companies, raw)
        except Exception as e:
            self.logger.warning("DiscoveryAgent: JSON extraction failed — %s", e)
            return []

    def _extract_companies_from_html(self, html: str, event_name: str) -> list[dict]:
        truncated = html[:40000]

        icp = self.config.get("icp", {})
        industry = self.config.get("research", {}).get("industry", {})
        verticals = industry.get("verticals", [])
        buyer_kws = industry.get("buyer_keywords", [])

        system_prompt = (
            "You are a data extraction assistant. You extract exhibiting company names from HTML. "
            "You return JSON only."
        )
        user_prompt = f"""
Extract exhibiting company names from this HTML from the {event_name} exhibitor page.
Focus on companies relevant to: {icp.get("description", "graphics, signage, wide-format printing, protective films, or vehicle wraps")}
Target verticals: {", ".join(verticals[:5])}
Target buyer types: {", ".join(buyer_kws[:4])}
Ignore navigation items, sponsors sections, and generic page elements.

CRITICAL RULES — violation means wrong output:
- ONLY include companies whose exact name appears verbatim in the HTML below
- DO NOT infer, guess, complete, or add any company name not literally present in the HTML
- If a company name is ambiguous or partial, skip it
- Return empty list if no clear company names are found

Return JSON:
{{
  "companies": [
    {{"name": "Exact Company Name As It Appears", "website": "https://... or null", "description": "one line or null"}}
  ]
}}

HTML:
{truncated}
"""
        try:
            result = self.call_llm(system_prompt, user_prompt)
            companies = result.get("companies", [])
            return self._verbatim_filter(companies, truncated)
        except Exception as e:
            self.logger.warning("DiscoveryAgent: HTML extraction failed — %s", e)
            return []

    def _extract_companies_from_text(self, text: str, event_name: str) -> list[dict]:
        """
        Extracts companies from plain page text (e.g. MapYourShow inner_text).
        Cleaner than HTML parsing for paginated exhibitor galleries.
        """
        truncated = text[:50000]

        icp = self.config.get("icp", {})
        industry = self.config.get("research", {}).get("industry", {})
        verticals = industry.get("verticals", [])
        buyer_kws = industry.get("buyer_keywords", [])

        system_prompt = (
            "You are a data extraction assistant. You extract exhibiting company names from page text. "
            "You return JSON only."
        )
        user_prompt = f"""
Extract exhibiting company names from this page text from the {event_name} exhibitor directory.
Focus on companies relevant to: {icp.get("description", "graphics, signage, wide-format printing, protective films, or vehicle wraps")}
Target verticals: {", ".join(verticals[:5])}
Target buyer types: {", ".join(buyer_kws[:4])}

Ignore navigation text, filter labels (like "Filter by Alpha", "Load More"), and footer content.

CRITICAL RULES — violation means wrong output:
- ONLY include companies whose exact name appears verbatim in the text below
- DO NOT infer, guess, complete, or add any company name not literally present in the text
- Return empty list if no clear company names are found

Return JSON:
{{
  "companies": [
    {{"name": "Exact Company Name As It Appears", "website": null, "description": null}}
  ]
}}

Page text:
{truncated}
"""
        try:
            result = self.call_llm(system_prompt, user_prompt)
            companies = result.get("companies", [])
            return self._verbatim_filter(companies, truncated)
        except Exception as e:
            self.logger.warning("DiscoveryAgent: text extraction failed — %s", e)
            return []

    # ------------------------------------------------------------------
    # Serper fallback
    # ------------------------------------------------------------------

    def _serper_search(self, query: str, event_name: str) -> list[dict]:
        self.logger.info("DiscoveryAgent: Serper → '%s'", query)
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            return []

        try:
            response = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 20},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as e:
            self.logger.warning("DiscoveryAgent: Serper failed — %s", e)
            return []

        snippets = [
            f"{item.get('title', '')} — {item.get('snippet', '')} ({item.get('link', '')})"
            for item in results.get("organic", [])
        ]

        if not snippets:
            return []

        joined = "\n".join(snippets[:30])

        # Pull ICP signals from config for targeted extraction
        icp = self.config.get("icp", {})
        industry = self.config.get("research", {}).get("industry", {})
        verticals = industry.get("verticals", [])
        buyer_kws = industry.get("buyer_keywords", [])
        ideal_signals = icp.get("ideal_signals", [])
        icp_description = icp.get("description", "")

        system_prompt = "You are a B2B data extraction assistant. You return JSON only."
        user_prompt = f"""
From these search results about {event_name}, extract company names that are relevant
potential customers for a company selling to: {icp_description}

TARGET company types (only include companies that clearly fit one of these):
- Industry verticals: {", ".join(verticals)}
- Buyer types: {", ".join(buyer_kws)}
- Ideal signals: {", ".join(ideal_signals)}

EXCLUDE companies that are clearly:
- Pure software vendors (RIP software, workflow software, print management tools)
- Spectrophotometer or measurement instrument makers (unless also doing graphics)
- Automotive distributors or dealers
- PR/marketing agencies
- Trade show organizers themselves

CRITICAL RULES — violation means wrong output:
- ONLY include companies whose exact name appears verbatim in the search results below
- DO NOT infer, guess, complete, or add any company name not literally present in the text
- DO NOT include generic descriptors like "Sign Company" or "Print Solutions" unless that is the actual registered company name present in the text
- If results are thin or ambiguous, return fewer companies — an empty list is better than invented names
- Return empty list if no clear exhibitor names are found

Results:
{joined}

Return JSON:
{{
  "companies": [
    {{"name": "Exact Company Name As It Appears", "website": "https://... or null", "description": "one line or null"}}
  ]
}}
"""
        try:
            result = self.call_llm(system_prompt, user_prompt)
            companies = result.get("companies", [])
            return self._verbatim_filter(companies, joined)
        except Exception as e:
            self.logger.warning("DiscoveryAgent: snippet extraction failed — %s", e)
            return []

    # ------------------------------------------------------------------
    # Verbatim filter — rejects any company name the LLM invented
    # ------------------------------------------------------------------

    def _verbatim_filter(self, companies: list[dict], source_text: str) -> list[dict]:
        """
        Hard check: the company name must appear literally in the source text.
        Catches hallucinated names the LLM generates when source is thin.
        Case-insensitive, strips common suffixes for fuzzy but grounded matching.
        """
        source_lower = source_text.lower()
        kept = []
        for company in companies:
            name = (company.get("name") or "").strip()
            if not name:
                continue
            # Check full name, then progressively shorter versions (handles "Inc.", "Ltd.", etc.)
            variants = [
                name.lower(),
                name.lower().rstrip("."),
            ]
            # Also try stripping common legal suffixes
            for suffix in [" inc", " inc.", " ltd", " ltd.", " llc", " corp", " co.", " co"]:
                variants.append(name.lower().replace(suffix, "").strip())

            if any(v in source_lower for v in variants if len(v) >= 4):
                kept.append(company)
            else:
                self.logger.warning(
                    "DiscoveryAgent: rejected '%s' — name not found verbatim in source", name
                )
        self.logger.info(
            "DiscoveryAgent: verbatim filter kept %d/%d companies", len(kept), len(companies)
        )
        return kept
