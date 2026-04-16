import os
import httpx
from agents.base_agent import BaseAgent


class ResearchAgent(BaseAgent):
    model_key = "research"
    """
    Dynamically discovers trade events relevant to DuPont Tedlar's ICP
    using Serper search — no hardcoded event list.

    Flow:
      1. Run multiple search queries via Serper
      2. Collect all search result snippets
      3. LLM filters to relevant events and extracts structured data
         (name, url, exhibitor_page, location, date, relevance)
    """

    def run(self) -> list[dict]:
        research_cfg  = self.config["research"]
        industry      = research_cfg["industry"]
        max_events    = research_cfg["max_events"]

        # Build search queries dynamically from industry config — no hardcoding
        queries = self._build_queries(industry)
        self.logger.info("ResearchAgent: searching with %d dynamic queries", len(queries))

        all_snippets = []
        for query in queries:
            snippets = self._serper_search(query)
            all_snippets.extend(snippets)
            self.logger.info("ResearchAgent: '%s' → %d results", query, len(snippets))

        if not all_snippets:
            self.logger.error("ResearchAgent: no search results returned")
            return []

        events = self._extract_events(all_snippets, industry, max_events)
        self.logger.info("ResearchAgent: discovered %d relevant events", len(events))
        return events

    def _build_queries(self, industry: dict) -> list[str]:
        """
        Builds search queries in two layers:

        Layer 1 — Seed events (anchors): searches for the most recent edition
        of known high-value events by name. This guarantees the pipeline always
        finds the right shows regardless of what Google organically surfaces.
        No year is hardcoded — "most recent exhibitors" finds the latest edition.

        Layer 2 — Dynamic discovery: broad industry queries that can surface
        new events the seed list doesn't know about yet.
        """
        seed_events = self.config.get("research", {}).get("seed_events", [])
        verticals   = industry.get("verticals", [])
        buyer_kws   = industry.get("buyer_keywords", [])

        queries = []

        # Layer 1: one query per seed event — finds the most recent edition
        for event in seed_events:
            queries.append(f'"{event}" exhibitors most recent')

        # Layer 2: broad industry queries for net-new event discovery
        for vertical in verticals[:2]:
            queries.append(f"{vertical} trade show expo exhibitors USA")

        for kw in buyer_kws[:2]:
            queries.append(f"{kw} industry expo conference exhibitors USA")

        return queries

    def _serper_search(self, query: str) -> list[str]:
        api_key = os.environ.get("SERPER_API_KEY")
        if not api_key:
            self.logger.warning("ResearchAgent: SERPER_API_KEY not set")
            return []

        try:
            response = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 10},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json()
        except Exception as e:
            self.logger.warning("ResearchAgent: Serper failed for '%s' — %s", query, e)
            return []

        snippets = []
        for item in results.get("organic", []):
            snippets.append(
                f"TITLE: {item.get('title', '')}\n"
                f"URL: {item.get('link', '')}\n"
                f"SNIPPET: {item.get('snippet', '')}"
            )
        return snippets

    def _extract_events(self, snippets: list[str], industry: dict, max_events: int) -> list[dict]:
        joined = "\n---\n".join(snippets[:40])
        criteria       = self.config["research"].get("event_criteria", {})
        min_exhibitors = criteria.get("min_exhibitor_count", 50)
        geography      = criteria.get("geography", "US-based")
        exclude_regions = criteria.get("exclude_regions", [])
        exclude_types   = criteria.get("exclude_types", [])
        verticals       = industry.get("verticals", [])
        buyer_keywords  = industry.get("buyer_keywords", [])

        system_prompt = (
            "You are a B2B market research assistant specializing in the graphics, signage, "
            "and protective films industry. You return JSON only."
        )

        user_prompt = f"""
From these search results, extract the most relevant trade events for a company selling:
{industry.get("description", "")}

Target industry verticals: {", ".join(verticals)}
Target buyers: {", ".join(buyer_keywords)}

QUALITY CRITERIA — only include events that meet ALL of these:
1. At least {min_exhibitors} exhibitors — major trade shows only, not small conferences
2. Geography: {geography}
3. Core audience must overlap with the target verticals above
4. Real verifiable trade show with an exhibitor list — not an article, award show, or webinar

EXCLUDE:
- Regions: {", ".join(exclude_regions)}
- Event types: {", ".join(exclude_types)}
- Any event you are not confident has 50+ relevant exhibitors

For each event extract: official name, website URL, exhibitor list page URL, location, date, and why it's relevant.

CRITICAL for exhibitor_page URL:
- Find the PUBLIC EXHIBITOR DIRECTORY where visitors can browse/search exhibiting companies.
- This is NOT the "Exhibitor Resource Center" or "Exhibitor Services" page (those are for registered exhibitors to manage logistics).
- Many shows use mapyourshow.com for their directory — look for URLs containing "mapyourshow.com", "exhibitor-gallery", "exhibitors.cfm", or "exhibitor-list".
- Example good URLs: https://isasignexpo2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm, https://show.mapyourshow.com/explore/exhibitor-gallery.cfm
- Example BAD URLs: signexpo.org/current-exhibitors/ (resource center), any page requiring login

Up to {max_events} events. Return fewer if quality requires — do not pad with low-quality shows.

Search results:
{joined}

Return JSON:
{{
  "events": [
    {{
      "name": "ISA International Sign Expo 2025",
      "url": "https://www.signexpo.org",
      "exhibitor_page": "https://www.signexpo.org/en/exhibitors.html",
      "location": "Las Vegas, NV",
      "date": "April 2025",
      "relevance": "..."
    }}
  ]
}}
"""
        result = self.call_llm(system_prompt, user_prompt)
        return result.get("events", [])
