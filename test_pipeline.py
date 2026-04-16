"""
Phase 2 end-to-end test.
Runs one event through ResearchAgent → DiscoveryAgent → EnrichmentAgent.
Saves output to outputs/test_run.json and prints a summary.

Usage:
    python3 test_pipeline.py                  # uses ISA Sign Expo (first event)
    python3 test_pipeline.py --event "FESPA"  # match by name substring
"""

import argparse
import json
import os
from datetime import datetime

from agents.research_agent import ResearchAgent
from agents.discovery_agent import DiscoveryAgent
from agents.enrichment_agent import EnrichmentAgent

os.makedirs("outputs", exist_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=None, help="Event name substring to test (default: first event)")
    args = parser.parse_args()

    with open("config.json") as f:
        config = json.load(f)

    # ── Step 1: Research ───────────────────────────────────────────────
    print("\n[1/3] ResearchAgent — enriching events...")
    research = ResearchAgent(config)
    events = research.run()

    # Pick one event
    if args.event:
        matched = [e for e in events if args.event.lower() in e["name"].lower()]
        if not matched:
            print(f"No event matching '{args.event}'. Available:")
            for e in events:
                print(f"  - {e['name']}")
            return
        event = matched[0]
    else:
        event = events[0]

    print(f"    Testing with: {event['name']}")
    print(f"    Relevance: {event.get('relevance', 'n/a')}\n")

    # ── Step 2: Discovery ──────────────────────────────────────────────
    print("[2/3] DiscoveryAgent — finding companies...")
    discovery = DiscoveryAgent(config)
    companies = discovery.run([event])

    if not companies:
        print("    No companies found. Possible causes:")
        print("    - Exhibitor page blocked Playwright")
        print("    - SERPER_API_KEY not set in .env")
        print("    - Event has no exhibitor_page and Serper returned nothing")
        return

    print(f"    Found {len(companies)} companies")
    for c in companies[:5]:
        print(f"      • {c['name']} ({c['discovery_confidence']})")
    if len(companies) > 5:
        print(f"      ... and {len(companies) - 5} more\n")

    # ── Step 3: Enrichment ─────────────────────────────────────────────
    print(f"\n[3/3] EnrichmentAgent — scoring {len(companies)} companies...")
    enrichment = EnrichmentAgent(config)
    leads = enrichment.run(companies)

    threshold = config["icp"]["icp_score_threshold"]
    qualified = [l for l in leads if l["icp_score"] >= threshold]

    print(f"\n── Results ──────────────────────────────────────────")
    print(f"  Total enriched : {len(leads)}")
    print(f"  Above threshold ({threshold}): {len(qualified)}")
    print()

    # Sort by score descending
    leads.sort(key=lambda x: x["icp_score"], reverse=True)
    for lead in leads:
        flag = "✓" if lead["icp_score"] >= threshold else "✗"
        breakdown = lead["icp_breakdown"]
        print(
            f"  {flag} {lead['company']:<40} score={lead['icp_score']:.3f}  "
            f"ind={breakdown['industry_fit']}  rev={breakdown['revenue_tier']}  "
            f"evt={breakdown['event_confirmation']}  ovlp={breakdown['product_overlap']}"
        )
        if lead.get("qualification_rationale"):
            print(f"      {lead['qualification_rationale'][:120]}")

    # ── Save output ────────────────────────────────────────────────────
    out = {
        "run_at": datetime.utcnow().isoformat(),
        "event_tested": event["name"],
        "companies_found": len(companies),
        "leads_qualified": len(qualified),
        "leads": leads,
    }
    out_path = "outputs/test_run.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    print(f"\n  Full output saved → {out_path}")


if __name__ == "__main__":
    main()
