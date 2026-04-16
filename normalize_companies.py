"""
normalize_companies.py
----------------------
One-time script to fix company names already stored in the DB.
Problems it solves:
  - "3M Graphic & Visual Solutions", "3M Commercial Graphics" → company="3M", division=...
  - "Avery Dennison Graphics Solutions" stored as company → company="Avery Dennison", division=...
  - Hallucinated/non-existent companies (e.g. "Wide-Format Wonders") → mark for deletion

Usage:
  python normalize_companies.py           # dry-run: shows what would change
  python normalize_companies.py --apply   # writes changes to DB
"""

import sys
from dotenv import load_dotenv

load_dotenv()

# ── Known normalizations (deterministic, no LLM needed) ──────────────────────
# Format: { "stored name (lowercase)": ("Root Parent", "Division or None") }
KNOWN = {
    "3m graphic & visual solutions":      ("3M", "3M Graphic & Visual Solutions"),
    "3m commercial graphics":             ("3M", "3M Commercial Graphics"),
    "3m graphic solutions":               ("3M", "3M Graphic Solutions"),
    "3m graphics":                        ("3M", "3M Graphics"),
    "avery dennison graphics solutions":  ("Avery Dennison", "Avery Dennison Graphics Solutions"),
    "avery dennison graphics":            ("Avery Dennison", "Avery Dennison Graphics"),
    "fujifilm dimatix":                   ("Fujifilm", "Fujifilm Dimatix"),
    "fujifilm graphic systems":           ("Fujifilm", "Fujifilm Graphic Systems"),
    "hp large format printing":           ("HP Inc.", "HP Large Format Printing"),
    "hp inc large format":                ("HP Inc.", "HP Large Format Printing"),
    "epson america":                      ("Epson", "Epson America"),
    "canon solutions america":            ("Canon", "Canon Solutions America"),
    "dupont performance films":           ("DuPont", "DuPont Performance Films"),
    "dupont tedlar":                      ("DuPont", "DuPont Tedlar"),
}

# ── Suspected hallucinations — flag for review ────────────────────────────────
SUSPECTED_FAKE = {
    "wide-format wonders",
    "protective films ltd",
    "protective films ltd.",
    "protective film solutions",
    "graphic overlay solutions",
    "signage solutions inc",
    "print solutions group",
}


def main():
    apply = "--apply" in sys.argv

    from db import get_client
    client_db = get_client()

    # Fetch all leads
    rows = client_db.table("leads").select("id, company, division, event_source").execute().data
    print(f"Fetched {len(rows)} leads from DB\n")

    changes = []
    fakes = []

    for row in rows:
        stored_name = row["company"] or ""
        stored_div  = row["division"]
        key = stored_name.strip().lower()

        # 1. Check suspected hallucinations first
        if key in SUSPECTED_FAKE:
            fakes.append(row)
            print(f"  [FAKE?] '{stored_name}' (id={row['id'][:8]}…) — mark for deletion")
            continue

        # 2. Known deterministic mapping only — no LLM fallback for unknowns
        #    LLM was incorrectly mapping real standalone companies (Oracal, Roland DGA, etc.)
        #    to wrong parents. Only apply changes we are 100% sure about.
        if key not in KNOWN:
            continue  # leave unknown companies as-is

        new_company, new_division = KNOWN[key]

        # Only record if something actually changes
        company_changed = new_company != stored_name
        division_changed = new_division != stored_div

        if company_changed or division_changed:
            changes.append({
                "id":           row["id"],
                "old_company":  stored_name,
                "old_division": stored_div,
                "new_company":  new_company,
                "new_division": new_division,
            })
            marker = " ← CHANGED" if company_changed else ""
            print(
                f"  company: '{stored_name}' → '{new_company}'{marker}\n"
                f"  division: '{stored_div}' → '{new_division}'\n"
                f"  event: {row['event_source']}  id={row['id'][:8]}…\n"
            )

    print(f"\n{'='*60}")
    print(f"  {len(changes)} leads to rename")
    print(f"  {len(fakes)} suspected hallucinations")
    print(f"{'='*60}")

    if not apply:
        print("\nDry-run — no changes written. Re-run with --apply to commit.")
        return

    # ── Apply renames ──────────────────────────────────────────
    for c in changes:
        client_db.table("leads").update({
            "company":  c["new_company"],
            "division": c["new_division"],
        }).eq("id", c["id"]).execute()
    print(f"\nRenamed {len(changes)} leads.")

    # ── Print fake IDs (don't auto-delete — let human confirm) ──
    if fakes:
        print("\nSuspected hallucinated companies (NOT auto-deleted — review and delete manually):")
        for f in fakes:
            print(f"  id={f['id']}  company='{f['company']}'  event='{f['event_source']}'")
        print("\nTo delete them, run in Supabase SQL editor:")
        ids = ", ".join(f"'{f['id']}'" for f in fakes)
        print(f"  DELETE FROM contacts WHERE lead_id IN ({ids});")
        print(f"  DELETE FROM leads WHERE id IN ({ids});")


if __name__ == "__main__":
    main()
