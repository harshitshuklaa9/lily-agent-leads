from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.base_agent import BaseAgent


class EnrichmentAgent(BaseAgent):
    model_key = "enrichment"
    """
    Enriches each company with ICP scoring.

    Scoring weights (from config):
      industry_fit       40%
      revenue_tier       25%
      event_confirmation 20%
      product_overlap    15%

    Runs up to 5 companies in parallel via ThreadPoolExecutor.
    Only companies scoring above icp_score_threshold are surfaced in the dashboard.
    """

    def run(self, companies: list[dict]) -> list[dict]:
        weights = self.config["scoring_weights"]
        threshold = self.config["icp"]["icp_score_threshold"]
        max_workers = self.config.get("parallel", {}).get("enrichment_workers", 5)

        def enrich_one(company):
            self.logger.info("EnrichmentAgent: enriching '%s'", company.get("name"))
            try:
                lead = self._enrich(company, weights)
            except Exception as e:
                self.logger.error("EnrichmentAgent: failed on '%s' — %s", company.get("name"), e)
                lead = self._fallback_lead(company)
            self.logger.info(
                "EnrichmentAgent: '%s' scored %.3f — %s",
                lead["company"], lead["icp_score"],
                "PASS" if lead["icp_score"] >= threshold else "below threshold"
            )
            return lead

        enriched = [None] * len(companies)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(enrich_one, c): i for i, c in enumerate(companies)}
            for future in as_completed(futures):
                enriched[futures[future]] = future.result()

        return enriched

    def _enrich(self, company: dict, weights: dict) -> dict:
        icp = self.config["icp"]
        revenue_tiers = self.config["revenue_tiers"]
        confirmation_scores = self.config["event_confirmation_scores"]
        discovery_confidence = company.get("discovery_confidence", "low_confidence")

        seller = self.config.get("seller", {})
        verticals = self.config.get("research", {}).get("industry", {}).get("verticals", [])

        system_prompt = (
            f"You are a B2B sales intelligence analyst helping {seller.get('company', 'a company')} "
            f"identify potential customers for {seller.get('product', 'their product')}. "
            "You return JSON only."
        )

        user_prompt = f"""
Analyze this company and score their fit as a potential customer for {self.config.get("seller", {}).get("company", "our company")} — {self.config.get("seller", {}).get("product", "")}.

Company info:
- Name: {company.get("name")}
- Website: {company.get("website")}
- Description: {company.get("description")}
- Discovered at event: {company.get("event_source")}

ICP context:
- Target: {icp["description"]}
- Ideal signals: {", ".join(icp["ideal_signals"])}
- Key value props: {", ".join(self.config.get("seller", {}).get("value_props", []))}

Scoring instructions:
1. industry_fit (0.0-1.0): Does their core business involve any of these: {", ".join(verticals)}?
2. revenue_tier: Use ONLY these exact values — under $10M = {revenue_tiers["under_10m"]}, $10M-$100M = {revenue_tiers["10m_to_100m"]}, over $100M = {revenue_tiers["over_100m"]}. If revenue is unknown or uncertain, default to {revenue_tiers["under_10m"]} (under $10M). NEVER return 0.0.
3. product_overlap (0.0-1.0): How closely do they use or sell products related to: {icp["description"]}?

Company name normalization rules — CRITICAL:
- The "company" field MUST be the ROOT PARENT company name only.
  Examples: "3M" (not "3M Graphic & Visual Solutions"), "Avery Dennison" (not "Avery Dennison Graphics Solutions"), "Fujifilm" (not "Fujifilm Dimatix")
  If the input name IS a division name, look up and return the parent corporation.
- The "division" field is the specific business unit that would actually purchase this product.
  Examples: "3M Graphic & Visual Solutions", "Avery Dennison Graphics Solutions"
  If the entire company is the buyer with no relevant sub-division, set division to null.

Return JSON:
{{
  "company": "Root Parent Company Name",
  "division": "Specific Division Name or null",
  "website": "...",
  "revenue_estimate": "$XM or $XB range",
  "icp_breakdown": {{
    "industry_fit": 0.0,
    "revenue_tier": 0.0,
    "product_overlap": 0.0
  }},
  "qualification_rationale": "2-3 sentences explaining the score"
}}
"""
        result = self.call_llm(system_prompt, user_prompt)

        # Pull LLM scores
        breakdown = result.get("icp_breakdown", {})
        industry_fit = float(breakdown.get("industry_fit", 0.0))
        revenue_tier = float(breakdown.get("revenue_tier", 0.0))
        product_overlap = float(breakdown.get("product_overlap", 0.0))

        # Event confirmation score comes from discovery, not LLM
        event_confirmation = confirmation_scores.get(discovery_confidence, 0.0)

        # Weighted final score
        icp_score = (
            industry_fit       * weights["industry_fit"] +
            revenue_tier       * weights["revenue_tier"] +
            event_confirmation * weights["event_confirmation"] +
            product_overlap    * weights["product_overlap"]
        )
        icp_score = round(min(icp_score, 1.0), 3)

        # Normalise division — LLM sometimes returns the string "null" instead of JSON null
        raw_division = result.get("division")
        division = raw_division if raw_division and str(raw_division).lower() not in ("null", "none", "") else None

        return {
            "company":               result.get("company", company.get("name")),
            "division":              division,
            "event_source":          company.get("event_source"),
            "discovery_confidence":  discovery_confidence,
            "revenue_estimate":      result.get("revenue_estimate"),
            "icp_score":             icp_score,
            "icp_breakdown": {
                "industry_fit":       industry_fit,
                "revenue_tier":       revenue_tier,
                "event_confirmation": event_confirmation,
                "product_overlap":    product_overlap,
            },
            "qualification_rationale": result.get("qualification_rationale"),
            "contacts": [],
        }

    def _fallback_lead(self, company: dict) -> dict:
        """Returns a minimal lead with null scores when enrichment fails."""
        return {
            "company":               company.get("name"),
            "division":              None,
            "event_source":          company.get("event_source"),
            "discovery_confidence":  company.get("discovery_confidence", "low_confidence"),
            "revenue_estimate":      None,
            "icp_score":             0.0,
            "icp_breakdown": {
                "industry_fit":       None,
                "revenue_tier":       None,
                "event_confirmation": None,
                "product_overlap":    None,
            },
            "qualification_rationale": None,
            "contacts": [],
        }
