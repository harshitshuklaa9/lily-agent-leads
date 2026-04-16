import os
import re
import httpx
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.base_agent import BaseAgent


# ---------------------------------------------------------------------------
# Integration providers — checked in order of preference.
# Keys are stored in the Supabase `settings` table and configurable
# via the Integrations panel in the dashboard.
# If no key is present, falls back to the Serper/Google scraper.
# ---------------------------------------------------------------------------

def _linkedin_sales_nav_search(company: str, title_keywords: list[str], token: str) -> list[dict]:
    """LinkedIn Sales Navigator People Search API."""
    try:
        response = httpx.post(
            "https://api.linkedin.com/v2/salesNavigatorLeadSearch",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={
                "query": {
                    "companyName": company,
                    "titleKeywords": " OR ".join(title_keywords),
                    "geoRegion": "us:0",
                },
                "count": 5,
            },
            timeout=15,
        )
        response.raise_for_status()
        elements = response.json().get("elements", [])
        return [
            {
                "name": f"{e.get('firstName', '')} {e.get('lastName', '')}".strip(),
                "title": e.get("title", ""),
                "linkedin_url": e.get("publicProfileUrl", ""),
                "snippet": e.get("headline", ""),
            }
            for e in elements
            if e.get("firstName")
        ]
    except Exception:
        return []


def _clay_people_search(company: str, title_keywords: list[str], api_key: str) -> list[dict]:
    """Clay People Search API."""
    try:
        response = httpx.post(
            "https://api.clay.com/v1/search/people",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"company_name": company, "titles": title_keywords, "limit": 5},
            timeout=15,
        )
        response.raise_for_status()
        people = response.json().get("data", [])
        return [
            {
                "name": p.get("name", ""),
                "title": p.get("title", ""),
                "linkedin_url": p.get("linkedin_url", ""),
                "snippet": p.get("bio", ""),
            }
            for p in people
            if p.get("name")
        ]
    except Exception:
        return []


def _apollo_people_search(company: str, title_keywords: list[str], api_key: str) -> list[dict]:
    """Apollo.io People Search API (free tier available)."""
    try:
        response = httpx.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
            json={
                "api_key": api_key,
                "q_organization_name": company,
                "person_titles": title_keywords,
                "page": 1,
                "per_page": 5,
            },
            timeout=15,
        )
        response.raise_for_status()
        people = response.json().get("people", [])
        return [
            {
                "name": p.get("name", ""),
                "title": p.get("title", ""),
                "linkedin_url": p.get("linkedin_url", ""),
                "snippet": p.get("headline", ""),
            }
            for p in people
            if p.get("name")
        ]
    except Exception:
        return []
# ---------------------------------------------------------------------------


class StakeholderAgent(BaseAgent):
    model_key = "stakeholder"
    """
    Finds real decision makers per lead using Serper → Google → LinkedIn search.

    Strategy:
      - 2 batched Serper queries per company (technical + business), down from 4.
        Each query uses broader OR terms to cast a wider net in one API call.
      - LLM (gpt-4o-mini) picks the best technical and best business contact
        from all results combined.
      - Companies processed in parallel (default 3 workers) — rate-limited
        to avoid hammering Serper simultaneously.

    Note: Playwright/headless browser search was evaluated but abandoned — both
    Bing and DuckDuckGo block headless requests without a residential proxy.
    Playwright remains available in DiscoveryAgent for scraping known exhibitor pages.
    """

    def run(self, leads: list[dict]) -> list[dict]:
        max_workers = self.config.get("parallel", {}).get("stakeholder_workers", 3)
        global_seen_urls: set[str] = set()
        lock = __import__("threading").Lock()

        # Group leads by company name — search ONCE per company, not once per event.
        # e.g. 3M appearing at SEMA + ISA + PRINTING United = 1 Serper search, not 3.
        company_groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for i, lead in enumerate(leads):
            key = (lead.get("company") or "").strip().lower()
            company_groups[key].append((i, lead))

        processed = [None] * len(leads)

        def process_company(group_key: str, group_items: list[tuple[int, dict]]):
            representative = group_items[0][1]
            company_name   = representative.get("company", "")
            event_count    = len(group_items)

            self.logger.info(
                "StakeholderAgent: searching contacts for '%s' (%d event record%s)",
                company_name, event_count, "s" if event_count > 1 else ""
            )
            try:
                # Check DB first — another event record may already have fresh contacts
                existing = self._get_existing_contacts(company_name)
                if existing:
                    self.logger.info(
                        "StakeholderAgent: reusing %d existing DB contacts for '%s'",
                        len(existing), company_name
                    )
                    contacts = existing
                else:
                    contacts = self._find_contacts(representative)
                    # Deduplicate URLs across all companies in this run
                    unique = []
                    for c in contacts:
                        url = c.get("linkedin_url")
                        with lock:
                            if url and url in global_seen_urls:
                                self.logger.warning(
                                    "StakeholderAgent: skipping recycled contact %s at '%s'",
                                    c.get("name"), company_name
                                )
                                continue
                            if url:
                                global_seen_urls.add(url)
                        unique.append(c)
                    contacts = unique

                # Apply the same contacts to every event record for this company
                for i, lead in group_items:
                    lead["contacts"] = contacts
                    processed[i] = lead

                self.logger.info(
                    "StakeholderAgent: %d contacts → '%s' (applied to %d record%s)",
                    len(contacts), company_name, event_count, "s" if event_count > 1 else ""
                )
            except Exception as e:
                self.logger.error("StakeholderAgent: failed for '%s' — %s", company_name, e)
                for i, lead in group_items:
                    lead["contacts"] = []
                    processed[i] = lead

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(process_company, key, items): key
                for key, items in company_groups.items()
            }
            for future in as_completed(futures):
                future.result()

        return processed

    # ------------------------------------------------------------------
    # DB lookup — reuse contacts already found for this company
    # ------------------------------------------------------------------

    def _get_existing_contacts(self, company: str) -> list[dict]:
        """
        Returns contacts already stored for ANY lead with this company name.
        Prevents re-searching when the same company appears across multiple events.
        """
        try:
            import db as db_module
            return db_module.get_contacts_for_company(company)
        except Exception as e:
            self.logger.warning("StakeholderAgent: DB contact lookup failed — %s", e)
            return []

    # ------------------------------------------------------------------
    # Main contact finder — 2 batched searches, 1 LLM call each
    # ------------------------------------------------------------------

    def _find_contacts(self, lead: dict) -> list[dict]:
        raw_division = lead.get("division")
        division = raw_division if raw_division and str(raw_division).lower() not in ("null", "none", "") else None
        company = division or lead["company"]
        if division:
            self.logger.info(
                "StakeholderAgent: using division '%s' for '%s'",
                lead["division"], lead["company"]
            )

        # Load integration keys from environment variables (set in Railway)
        linkedin_token = os.environ.get("LINKEDIN_SALES_NAV_TOKEN")
        clay_key       = os.environ.get("CLAY_API_KEY")
        apollo_key     = os.environ.get("APOLLO_API_KEY")

        tech_titles = self.config.get("stakeholders", {}).get("technical_buyer_titles", [])
        biz_titles  = self.config.get("stakeholders", {}).get("business_buyer_titles", [])
        all_titles  = tech_titles + biz_titles

        # ── Provider routing ────────────────────────────────────────────
        if linkedin_token:
            self.logger.info("StakeholderAgent: using LinkedIn Sales Navigator for '%s'", company)
            raw = _linkedin_sales_nav_search(company, all_titles, linkedin_token)
            if raw:
                return self._split_by_buyer_type(raw, company, lead)

        if clay_key:
            self.logger.info("StakeholderAgent: using Clay API for '%s'", company)
            raw = _clay_people_search(company, all_titles, clay_key)
            if raw:
                return self._split_by_buyer_type(raw, company, lead)

        if apollo_key:
            self.logger.info("StakeholderAgent: using Apollo.io for '%s'", company)
            raw = _apollo_people_search(company, all_titles, apollo_key)
            if raw:
                return self._split_by_buyer_type(raw, company, lead)

        # ── Fallback: Serper/Google scraper ─────────────────────────────
        self.logger.info("StakeholderAgent: using Serper fallback for '%s'", company)
        contacts = []
        seen_urls: set[str] = set()

        tech_results = self._batch_serper_search(company, "technical")
        if tech_results:
            contact = self._pick_best(tech_results, company, "technical", lead)
            if contact and contact.get("linkedin_url") not in seen_urls:
                seen_urls.add(contact["linkedin_url"])
                contacts.append(contact)

        biz_results = self._batch_serper_search(company, "business")
        if biz_results:
            contact = self._pick_best(biz_results, company, "business", lead)
            if contact and contact.get("linkedin_url") not in seen_urls:
                seen_urls.add(contact["linkedin_url"])
                contacts.append(contact)

        if not contacts:
            self.logger.warning(
                "StakeholderAgent: no real contacts found for '%s' — leaving empty", company
            )

        return contacts

    def _split_by_buyer_type(self, raw: list[dict], company: str, lead: dict) -> list[dict]:
        """
        Takes raw API results and assigns buyer_type based on title matching.
        Returns at most one technical + one business contact.
        """
        tech_titles = [t.lower() for t in self.config.get("stakeholders", {}).get("technical_buyer_titles", [])]
        biz_titles  = [t.lower() for t in self.config.get("stakeholders", {}).get("business_buyer_titles", [])]

        contacts = []
        seen_types: set[str] = set()

        for person in raw:
            title_lower = (person.get("title") or "").lower()
            buyer_type = None

            for t in tech_titles:
                if any(word in title_lower for word in t.lower().split()):
                    buyer_type = "technical"
                    break
            if not buyer_type:
                for t in biz_titles:
                    if any(word in title_lower for word in t.lower().split()):
                        buyer_type = "business"
                        break
            if not buyer_type or buyer_type in seen_types:
                continue

            seen_types.add(buyer_type)
            contacts.append({
                "buyer_type":   buyer_type,
                "name":         person.get("name", ""),
                "title":        person.get("title", ""),
                "linkedin_url": person.get("linkedin_url", ""),
                "relevance":    person.get("snippet", ""),
            })

            if len(contacts) == 2:
                break

        return contacts

    # ------------------------------------------------------------------
    # Batched Serper search — 1 query covers all titles for a buyer type
    # ------------------------------------------------------------------

    def _batch_serper_search(self, company: str, buyer_type: str) -> list[dict]:
        """
        Single broad Serper query covering all title variants for a buyer type.
        Technical: VP or Director of engineering/materials/product/R&D
        Business:  VP or Director of operations/procurement/supply chain/sourcing
        """
        if buyer_type == "technical":
            titles = '"VP" OR "Director" engineering OR materials OR "R&D" OR product'
        else:
            titles = '"VP" OR "Director" operations OR procurement OR sourcing OR "supply chain"'

        query = f'{company} ({titles}) site:linkedin.com/in'
        self.logger.info("StakeholderAgent: batch search [%s] → %s", buyer_type, company)
        return self._serper_search(query, num=8)

    def _serper_search(self, query: str, num: int = 5) -> list[dict]:
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            return []

        try:
            response = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as e:
            self.logger.warning("StakeholderAgent: Serper failed — %s", e)
            return []

        contacts = []
        for item in results.get("organic", []):
            linkedin_url = item.get("link", "")
            if "linkedin.com/in/" not in linkedin_url:
                continue

            title_text = item.get("title", "")
            clean = title_text.replace(" | LinkedIn", "").strip()
            if " - " in clean:
                parts = clean.split(" - ", 1)
                name, title = parts[0].strip(), parts[1].strip()
            else:
                name, title = clean, ""

            if name:
                contacts.append({
                    "name": name,
                    "title": title,
                    "linkedin_url": linkedin_url,
                    "snippet": item.get("snippet", ""),
                })

        return contacts

    # ------------------------------------------------------------------
    # Employer extraction — parses "at Company" from LinkedIn title
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_employer(title: str) -> str | None:
        """
        Extracts the current employer from a parsed LinkedIn job title.
        Handles two common formats:
          "VP Engineering at Acme Corp"       → "Acme Corp"
          "Director of Operations · Acme Corp" → "Acme Corp"
        Also strips Serper artifacts like "- LinkedIn" at end of employer.
        Returns None if no employer signal found.
        """
        for sep in [" at ", " · "]:
            if sep in title:
                employer = title.split(sep, 1)[-1].strip()
                # Strip trailing Serper artifacts: "Company - LinkedIn", "Company | LinkedIn"
                import re as _re
                employer = _re.sub(r'\s*[-|]\s*(LinkedIn|Linkedin).*$', '', employer).strip()
                return employer if employer else None
        return None

    @staticmethod
    def _employer_matches_company(employer: str, company: str) -> bool:
        """
        Checks whether the extracted employer is the target company or a
        division/subsidiary of it. Uses normalised substring matching so
        "Avery Dennison Graphics Solutions" passes for target "Avery Dennison".
        """
        emp = employer.lower().strip()
        co  = company.lower().strip()

        # Strip common legal suffixes from both sides before comparing
        def strip_suffixes(s: str) -> str:
            return re.sub(
                r'\b(inc|llc|ltd|corp|co|group|solutions|systems|technologies|'
                r'international|usa|america|corporation)\.?\s*$',
                '', s
            ).strip()

        emp_core = strip_suffixes(emp)
        co_core  = strip_suffixes(co)

        # Either side contains the other (handles parent/division both ways)
        return co_core in emp_core or emp_core in co_core

    # ------------------------------------------------------------------
    # LLM validator — picks best match from batched results
    # ------------------------------------------------------------------

    def _pick_best(
        self,
        results: list[dict],
        company: str,
        buyer_type: str,
        lead: dict,
    ) -> dict | None:
        if not results:
            return None

        # Pre-filter: only pass candidates whose snippet/title mentions the company
        # as a standalone phrase — not as a substring of a different company's name.
        # e.g. "Graphics Co" must NOT match "Canon Graphics Corp" or "HP Graphics Co."
        company_lower = company.lower()
        # Strip legal suffixes to get the meaningful core name for matching
        core = re.sub(
            r'\b(inc|llc|ltd|corp|co|group|solutions|systems|technologies|international|usa|america)\.?\s*$',
            '', company_lower
        ).strip()
        # Also build a two-word short name for long company names
        core_words = core.split()
        short_core = " ".join(core_words[:2]) if len(core_words) > 2 else core

        def company_in_text(text: str) -> bool:
            """Word-boundary match — company name must appear as a standalone phrase."""
            t = text.lower()
            for phrase in [company_lower, core, short_core]:
                if len(phrase) < 4:
                    continue
                # \b word boundary on each side
                if re.search(r'\b' + re.escape(phrase) + r'\b', t):
                    return True
            return False

        verified = []
        for r in results:
            job_title = r.get("title", "")
            snippet   = r.get("snippet", "")

            # Layer 1: employer extracted directly from LinkedIn title ("at Company")
            # This is the strongest signal — deterministic, no LLM needed.
            employer = self._extract_employer(job_title)
            if employer is not None:
                if not self._employer_matches_company(employer, company):
                    self.logger.info(
                        "StakeholderAgent: rejected '%s' — employer '%s' ≠ '%s'",
                        r.get("name"), employer, company
                    )
                    continue
                # Employer confirmed — no need for snippet check
                verified.append(r)
                continue

            # Layer 2: fallback to word-boundary snippet check when title has no "at Company"
            text = f"{job_title} {snippet}"
            if company_in_text(text):
                verified.append(r)

        if not verified:
            self.logger.info(
                "StakeholderAgent: all %d candidates rejected — company name '%s' not in snippets",
                len(results), company
            )
            return None

        candidates = "\n".join(
            f"{i+1}. {r['name']} — {r['title']} | {r['linkedin_url']}\n   {r['snippet']}"
            for i, r in enumerate(verified)
        )

        technical_titles = self.config.get("stakeholders", {}).get("technical_buyer_titles", [])
        business_titles  = self.config.get("stakeholders", {}).get("business_buyer_titles", [])
        buyer_type_context = {
            "technical": f"evaluates technical specs and product decisions — titles like: {', '.join(technical_titles[:4])}",
            "business":  f"controls vendor selection, procurement and purchasing — titles like: {', '.join(business_titles[:4])}",
        }.get(buyer_type, buyer_type)

        system_prompt = "You are a B2B sales researcher. You return JSON only."
        user_prompt = f"""
I'm looking for a {buyer_type} contact at {company} for {self.config.get("seller", {}).get("company", "our company")} — {self.config.get("seller", {}).get("product", "")}.
Role context: {buyer_type_context}
Company context: {lead.get("qualification_rationale", "")}

Pick the BEST match — strict rules:
- Must CURRENTLY work at {company} as their PRIMARY employer — not a subsidiary, not a past role, not a company that merely has similar words in its name
- Title must be relevant to {buyer_type} decisions for {self.config.get("seller", {}).get("product", "this product")}
- Must be director-level or above
- If you have ANY doubt they work at {company} specifically, return null — a wrong person is worse than no person

If none clearly and confidently match {company}, return null.

Candidates:
{candidates}

Return JSON:
{{
  "selected": {{
    "buyer_type": "{buyer_type}",
    "name": "...",
    "title": "...",
    "linkedin_url": "https://linkedin.com/in/...",
    "relevance": "1-2 sentences why this person matters for {self.config.get('seller', {}).get('company', 'us')}"
  }}
}}

Or if no good match: {{"selected": null}}
"""
        try:
            result = self.call_llm(system_prompt, user_prompt)
            selected = result.get("selected")
            if not selected:
                return None
            url = selected.get("linkedin_url") or ""
            # Reject fake/constructed URLs — must be a real linkedin.com/in/ path
            if (
                not selected.get("name")
                or "linkedin.com/in/" not in url
                or "or null" in url.lower()
                or " " in url
                or len(url.split("/in/")[-1]) < 4  # slug too short to be real
            ):
                return None
            return selected
        except Exception as e:
            self.logger.warning("StakeholderAgent: LLM pick failed — %s", e)
            return None
