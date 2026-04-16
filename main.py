"""
Instalily Lead Gen Pipeline — DuPont Tedlar Graphics & Signage

Usage:
    python3 main.py              # smart run — skips what's already in DB
    python3 main.py --fresh      # force full re-run, overwrites everything
    python3 main.py --step enrich        # stop after enrichment
    python3 main.py --step stakeholders  # stop after stakeholder search
    python3 main.py --event "ISA"        # filter to one event

Smart run behaviour (default):
    Each step checks Supabase before doing work:

    Step 1 — ResearchAgent:
        If events were discovered in the last 24h → load from DB, skip agent.

    Step 2 — DiscoveryAgent:
        For each event, if leads already exist for that event_source → skip it.
        Only runs discovery on events with no companies yet.

    Step 3 — EnrichmentAgent:
        For each discovered company, if it's already scored in DB → skip it.
        Only scores new/unscored companies.

    Step 4 — StakeholderAgent:
        For each qualified lead, if it already has contacts → skip it.
        Only searches for contacts on leads that have none.

    Step 5 — OutreachAgent:
        For each contact, if outreach_subject + outreach_body are filled → skip it.
        Only writes emails for contacts with no outreach yet.

    Running daily: costs almost nothing for existing data.
    Running after a crash: picks up exactly where it left off.
    Use --fresh to force a full re-run (new events cycle, new company data).
"""

import argparse
import json
import logging
import os
from datetime import datetime, UTC

from agents.research_agent import ResearchAgent
from agents.discovery_agent import DiscoveryAgent
from agents.enrichment_agent import EnrichmentAgent
from agents.stakeholder_agent import StakeholderAgent
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

STEPS = ["research", "discover", "enrich", "stakeholders", "outreach"]

os.makedirs("outputs", exist_ok=True)


def load_config() -> dict:
    with open("config.json") as f:
        return json.load(f)


def save_debug(name: str, data) -> None:
    path = f"outputs/{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Debug snapshot saved → %s", path)


def main():
    parser = argparse.ArgumentParser(description="Instalily Lead Gen Pipeline")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Force full re-run — ignore all DB checkpoints"
    )
    parser.add_argument(
        "--step",
        choices=STEPS,
        default="outreach",
        help="Stop pipeline after this step (default: full pipeline)"
    )
    parser.add_argument(
        "--event",
        default=None,
        help="Only process events matching this substring"
    )
    args = parser.parse_args()
    smart = not args.fresh  # smart mode = use DB checkpoints

    config = load_config()
    threshold = config["icp"]["icp_score_threshold"]
    freshness = config.get("freshness", {})

    events_ttl    = freshness.get("events_max_age_hours",   168)   # 7 days
    leads_ttl     = freshness.get("leads_max_age_hours",    720)   # 30 days
    contacts_ttl  = freshness.get("contacts_max_age_hours", 336)   # 14 days

    # ── Step 1: Research ──────────────────────────────────────────────
    cached_events = db.get_recent_events(max_age_hours=events_ttl) if smart else []

    if cached_events:
        logger.info("=== STEP 1: ResearchAgent [SKIPPED — %d events in DB from last %dh] ===", len(cached_events), events_ttl)
        events = cached_events
    else:
        logger.info("=== STEP 1: ResearchAgent ===")
        events = ResearchAgent(config).run()
        db.upsert_events(events)
        save_debug("step1_events", events)

    if args.event:
        events = [e for e in events if args.event.lower() in e["name"].lower()]
        if not events:
            logger.error("No events matched '%s'", args.event)
            return
        logger.info("Filtered to %d event(s) matching '%s'", len(events), args.event)

    if args.step == "research":
        print(f"\nEvents found: {len(events)}")
        for e in events:
            print(f"  • {e['name']} — {e.get('relevance', '')[:80]}")
        return

    event_names = [e["name"] for e in events]

    # ── Step 2: Discovery ─────────────────────────────────────────────
    logger.info("=== STEP 2: DiscoveryAgent ===")

    # Only discover events that have no companies in DB yet
    if smart:
        existing_leads = db.get_leads_for_events(event_names)
        covered_events = {l["event_source"] for l in existing_leads}
        new_events = [e for e in events if e["name"] not in covered_events]
    else:
        existing_leads = []
        new_events = events

    if new_events:
        logger.info("Discovering companies for %d new event(s): %s",
                    len(new_events), [e["name"] for e in new_events])
        new_companies = DiscoveryAgent(config).run(new_events)
        save_debug("step2_companies", new_companies)
        logger.info("Discovered %d new companies", len(new_companies))
    else:
        new_companies = []
        logger.info("Discovery SKIPPED — all events already in DB")

    logger.info("Total companies for this run: %d new + %d from DB",
                len(new_companies), len(existing_leads))

    if args.step == "discover":
        print(f"\nNew companies discovered: {len(new_companies)}")
        for c in new_companies:
            print(f"  • {c['name']} ({c['discovery_confidence']}) — {c.get('event_source')}")
        return

    # ── Step 3: Enrichment ────────────────────────────────────────────
    logger.info("=== STEP 3: EnrichmentAgent ===")

    # Only enrich companies not already in DB
    if smart:
        to_enrich = [
            c for c in new_companies
            if not db.lead_exists(c["name"], c.get("event_source", ""), max_age_hours=leads_ttl)
        ]
    else:
        to_enrich = new_companies

    if to_enrich:
        logger.info("Enriching %d new companies", len(to_enrich))
        new_leads = EnrichmentAgent(config).run(to_enrich)
        save_debug("step3_leads", new_leads)
    else:
        new_leads = []
        logger.info("Enrichment SKIPPED — all companies already scored in DB")

    # Merge new leads with existing ones from DB
    all_leads = db.get_leads_for_events(event_names) if smart else new_leads
    if smart and new_leads:
        # Save new leads to DB so get_leads_for_events picks them up
        for lead in new_leads:
            try:
                db.upsert_lead(lead)
            except Exception as e:
                logger.error("Failed to save lead '%s': %s", lead.get("company"), e)
        all_leads = db.get_leads_for_events(event_names)

    qualified = [l for l in all_leads if l["icp_score"] >= threshold]
    logger.info("Total leads: %d | Qualified (≥%.1f): %d", len(all_leads), threshold, len(qualified))

    if args.step == "enrich":
        all_leads.sort(key=lambda x: x["icp_score"], reverse=True)
        print(f"\nLeads (≥{threshold} threshold):")
        for l in all_leads:
            flag = "✓" if l["icp_score"] >= threshold else "✗"
            print(f"  {flag} {l['company']:<40} {l['icp_score']:.3f}")
        return

    # ── Step 4: Stakeholders ──────────────────────────────────────────
    logger.info("=== STEP 4: StakeholderAgent ===")

    if smart:
        leads_needing_contacts = db.get_leads_without_contacts(event_names, max_age_hours=contacts_ttl)
        # Filter to qualified only
        leads_needing_contacts = [l for l in leads_needing_contacts if l["icp_score"] >= threshold]
    else:
        leads_needing_contacts = [l for l in qualified]

    if leads_needing_contacts:
        logger.info("Finding contacts for %d leads without contacts", len(leads_needing_contacts))
        leads_with_contacts = StakeholderAgent(config).run(leads_needing_contacts)
        save_debug("step4_stakeholders", leads_with_contacts)
        # Save contacts to DB immediately
        for lead in leads_with_contacts:
            try:
                lead_id = db.upsert_lead(lead)
                db.insert_contacts(lead.get("contacts", []), lead_id)
            except Exception as e:
                logger.error("Failed to save contacts for '%s': %s", lead.get("company"), e)
    else:
        logger.info("Stakeholder search SKIPPED — all qualified leads already have contacts")

    # Reload all leads with contacts from DB
    all_leads = db.get_leads_for_events(event_names) if smart else leads_with_contacts

    if args.step == "stakeholders":
        print(f"\nContacts found:")
        for l in all_leads:
            if l["icp_score"] < threshold:
                continue
            print(f"\n  {l['company']} (score: {l['icp_score']:.2f})")
            for c in l.get("contacts", []):
                print(f"    [{c['buyer_type']}] {c['name']} — {c['title']}")
        return

    # ── Step 5: Outreach ──────────────────────────────────────────────
    # Outreach emails are now generated on-demand per contact via the
    # dashboard (POST /contacts/:id/outreach). Not run in the pipeline
    # to avoid generating emails for contacts that are never used.
    logger.info("=== STEP 5: Outreach [SKIPPED — generated on-demand via dashboard] ===")

    # ── Final summary ─────────────────────────────────────────────────
    final_leads = db.get_leads_for_events(event_names)
    total_contacts = sum(len(l.get("contacts", [])) for l in final_leads)
    qualified_count = sum(1 for l in final_leads if l["icp_score"] >= threshold)

    print(f"""
╔══════════════════════════════════════════════╗
  Pipeline complete — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}
  Mode             : {'fresh (full re-run)' if args.fresh else 'smart (DB checkpoints)'}
  Events           : {len(events)}
  Total leads in DB: {len(final_leads)}
  Qualified (≥{threshold}) : {qualified_count}
  Total contacts   : {total_contacts}
╚══════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
