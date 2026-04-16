"""
Backfill contacts for leads in Supabase that have no contacts yet.
Runs StakeholderAgent + OutreachAgent only — no re-discovery.

Usage:
    python3 backfill_contacts.py
"""
import json
from db import get_client, insert_contacts
from agents.stakeholder_agent import StakeholderAgent
from agents.outreach_agent import OutreachAgent

with open("config.json") as f:
    config = json.load(f)

# Fetch leads with no contacts
client = get_client()
all_leads = client.table("leads").select("*, contacts(*)").execute().data
empty_leads = [l for l in all_leads if len(l.get("contacts", [])) == 0]

print(f"Found {len(empty_leads)} leads with no contacts:")
for l in empty_leads:
    print(f"  • {l['company']} ({l['event_source']}) — score: {l['icp_score']}")

if not empty_leads:
    print("Nothing to backfill.")
    exit()

# Reshape for agents (they expect icp_breakdown nested)
def reshape(lead):
    return {
        **lead,
        "icp_breakdown": {
            "industry_fit":       lead.get("industry_fit"),
            "revenue_tier":       lead.get("revenue_tier"),
            "event_confirmation": lead.get("event_confirmation"),
            "product_overlap":    lead.get("product_overlap"),
        },
        "contacts": []
    }

reshaped = [reshape(l) for l in empty_leads]

print("\nRunning StakeholderAgent...")
reshaped = StakeholderAgent(config).run(reshaped)

print("Running OutreachAgent...")
reshaped = OutreachAgent(config).run(reshaped)

print("\nSaving contacts to Supabase...")
for lead in reshaped:
    insert_contacts(lead["contacts"], lead["id"])
    print(f"  ✓ {lead['company']} — {len(lead['contacts'])} contacts saved")

print("\nDone.")
