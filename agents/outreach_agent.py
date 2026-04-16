from agents.base_agent import BaseAgent


class OutreachAgent(BaseAgent):
    model_key = "outreach"
    """
    Generates a personalized outreach email for each contact on a lead.

    Technical buyer angle: performance, durability, material specs
    Business buyer angle:  reliability, longevity, cost of replacement

    Format: subject line + 3-4 sentence email body
    References: event, company context, individual role
    """

    def run(self, leads: list[dict]) -> list[dict]:
        icp = self.config["icp"]

        for lead in leads:
            contacts = lead.get("contacts", [])
            if not contacts:
                self.logger.info("OutreachAgent: no contacts for '%s', skipping", lead["company"])
                continue

            self.logger.info(
                "OutreachAgent: generating outreach for '%s' (%d contacts)",
                lead["company"], len(contacts)
            )

            for contact in contacts:
                try:
                    subject, body = self._generate_email(lead, contact, icp)
                    contact["outreach_subject"] = subject
                    contact["outreach_body"] = body
                except Exception as e:
                    self.logger.error(
                        "OutreachAgent: failed for %s @ %s — %s",
                        contact.get("name"), lead["company"], e
                    )
                    contact["outreach_subject"] = None
                    contact["outreach_body"] = None

        return leads

    def _generate_email(self, lead: dict, contact: dict, icp: dict) -> tuple[str, str]:
        buyer_type = contact.get("buyer_type", "technical")

        if buyer_type == "technical":
            angle = (
                "Focus on: UV durability (12-20 years), material compatibility with their existing product line, "
                "film performance specs, non-PFAS formulation, and conformability for wraps. "
                "Speak to a materials or product engineering mindset."
            )
        else:
            angle = (
                "Focus on: supplier reliability, reduction in replacement cycles, total cost of ownership, "
                "procurement timeline advantages, and proven use with tier-1 graphic film manufacturers. "
                "Speak to an operations or procurement mindset."
            )

        seller = self.config.get("seller", {})
        seller_company = seller.get("company", "Our company")
        seller_product = seller.get("description", seller.get("product", ""))

        system_prompt = (
            f"You are a senior B2B sales writer for {seller_company}. "
            f"{seller_product} "
            "You write concise, specific, non-generic outreach emails. You return JSON only."
        )

        user_prompt = f"""
Write a personalized outreach email from {seller_company} to this contact.

Contact:
- Name: {contact.get("name")}
- Title: {contact.get("title")}
- Company: {lead["company"]}
- Why relevant: {contact.get("relevance")}

Context:
- Event where company was discovered: {lead.get("event_source")}
- Company revenue: {lead.get("revenue_estimate", "unknown")}
- ICP score: {lead.get("icp_score")}
- Rationale: {lead.get("qualification_rationale", "")}

Angle for this email:
{angle}

{self.config.get("seller", {}).get("company", "Our company")} key value props: {", ".join(self.config.get("seller", {}).get("value_props", []))}

Rules:
- Subject line: specific, not generic — reference the company or event
- Body: 3-4 sentences only
- Reference the event naturally (don't force it)
- Do NOT use filler phrases like "I hope this finds you well"
- End with a soft CTA (20-minute call, quick question, etc.)
- Use the contact's first name

Return JSON:
{{
  "subject": "...",
  "body": "..."
}}
"""
        result = self.call_llm(system_prompt, user_prompt)
        return result["subject"], result["body"]
