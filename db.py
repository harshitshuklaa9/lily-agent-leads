import json
import os
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = create_client(url, key)
    return _client


# ─────────────────────────────────────────────────────────────
# Events
# ─────────────────────────────────────────────────────────────

def upsert_events(events: list[dict]) -> None:
    """Save discovered events to DB. Updates if name already exists."""
    client = get_client()
    for event in events:
        payload = {
            "name":           event.get("name"),
            "url":            event.get("url"),
            "exhibitor_page": event.get("exhibitor_page"),
            "location":       event.get("location"),
            "date_info":      event.get("date"),
            "relevance":      event.get("relevance"),
            "discovered_at":  datetime.now(UTC).isoformat(),
        }
        existing = (
            client.table("events")
            .select("id")
            .eq("name", payload["name"])
            .execute()
        ).data
        if existing:
            client.table("events").update(payload).eq("id", existing[0]["id"]).execute()
        else:
            client.table("events").insert(payload).execute()


def get_recent_events(max_age_hours: int = 168) -> list[dict]:
    """
    Returns events discovered within the last max_age_hours (default 7 days).
    Returns empty list if no fresh events exist — caller should re-run ResearchAgent.
    """
    client = get_client()
    since = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
    rows = (
        client.table("events")
        .select("*")
        .gte("discovered_at", since)
        .execute()
    ).data

    # Normalise back to the shape agents expect
    return [
        {
            "name":           r["name"],
            "url":            r["url"],
            "exhibitor_page": r["exhibitor_page"],
            "location":       r["location"],
            "date":           r["date_info"],
            "relevance":      r["relevance"],
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────
# Leads
# ─────────────────────────────────────────────────────────────

def upsert_lead(lead: dict) -> str:
    """
    Insert or update a lead by (company, event_source).
    Returns the lead's UUID.
    """
    client = get_client()

    # Normalise division — guard against LLM returning "null" string
    raw_division = lead.get("division")
    division = raw_division if raw_division and str(raw_division).lower() not in ("null", "none", "") else None

    payload = {
        "company":                  lead.get("company"),
        "division":                 division,
        "event_source":             lead.get("event_source"),
        "discovery_confidence":     lead.get("discovery_confidence"),
        "revenue_estimate":         lead.get("revenue_estimate"),
        "icp_score":                lead.get("icp_score"),
        "industry_fit":             lead.get("icp_breakdown", {}).get("industry_fit"),
        "revenue_tier":             lead.get("icp_breakdown", {}).get("revenue_tier"),
        "event_confirmation":       lead.get("icp_breakdown", {}).get("event_confirmation"),
        "product_overlap":          lead.get("icp_breakdown", {}).get("product_overlap"),
        "qualification_rationale":  lead.get("qualification_rationale"),
        "updated_at":               datetime.now(UTC).isoformat(),
    }

    existing = (
        client.table("leads")
        .select("id")
        .eq("company", payload["company"])
        .eq("event_source", payload["event_source"])
        .execute()
    ).data

    if existing:
        lead_id = existing[0]["id"]
        client.table("leads").update(payload).eq("id", lead_id).execute()
        return lead_id

    result = client.table("leads").insert(payload).execute()
    return result.data[0]["id"]


def lead_exists(company: str, event_source: str, max_age_hours: int = 720) -> bool:
    """
    Returns True if this (company, event_source) pair is already enriched in DB
    and was scored within max_age_hours (default 30 days).
    A 0.0 score from a failed run is not counted as cached.
    """
    client = get_client()
    since = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
    rows = (
        client.table("leads")
        .select("id, icp_score, updated_at")
        .eq("company", company)
        .eq("event_source", event_source)
        .gte("updated_at", since)
        .execute()
    ).data
    return bool(rows and rows[0].get("icp_score", 0) > 0)


def get_leads_for_events(event_names: list[str]) -> list[dict]:
    """
    Returns all fully-enriched leads for the given events, with contacts nested.
    Used by main.py to load existing leads instead of re-enriching.
    """
    client = get_client()
    leads = (
        client.table("leads")
        .select("*, contacts(*)")
        .in_("event_source", event_names)
        .gt("icp_score", 0)
        .order("icp_score", desc=True)
        .execute()
    ).data
    return _normalise_leads(leads)


def get_leads_without_contacts(event_names: list[str], max_age_hours: int = 336) -> list[dict]:
    """
    Returns qualified leads that either have no contacts, or whose contacts are
    older than max_age_hours (default 14 days = stale, should re-search).
    StakeholderAgent should only run on these.
    """
    client = get_client()
    since = (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
    leads = (
        client.table("leads")
        .select("*, contacts(*)")
        .in_("event_source", event_names)
        .gt("icp_score", 0)
        .execute()
    ).data

    stale = []
    for lead in leads:
        contacts = lead.get("contacts", [])
        if not contacts:
            stale.append(lead)
            continue
        # If all contacts are older than the freshness window, re-search
        fresh_contacts = [
            c for c in contacts
            if c.get("created_at", "") >= since
        ]
        if not fresh_contacts:
            stale.append(lead)

    return _normalise_leads(stale)


def get_contacts_without_outreach(event_names: list[str]) -> list[dict]:
    """
    Returns leads where at least one contact is missing outreach copy.
    OutreachAgent should only run on these leads.
    """
    client = get_client()
    leads = (
        client.table("leads")
        .select("*, contacts(*)")
        .in_("event_source", event_names)
        .gt("icp_score", 0)
        .execute()
    ).data

    result = []
    for lead in leads:
        contacts = lead.get("contacts", [])
        incomplete = [
            c for c in contacts
            if not c.get("outreach_subject") or not c.get("outreach_body")
        ]
        if incomplete:
            normalised = _normalise_lead(lead)
            normalised["contacts"] = _normalise_contacts(incomplete)
            result.append(normalised)
    return result


# ─────────────────────────────────────────────────────────────
# Contacts
# ─────────────────────────────────────────────────────────────

def insert_contacts(contacts: list[dict], lead_id: str) -> None:
    """
    Insert contacts for a lead. Only replaces existing contacts if the new
    search actually found results — prevents concurrent runs from wiping
    valid contacts when one run finds nothing.
    """
    if not contacts:
        return  # never delete existing real contacts if new search found nothing

    client = get_client()
    client.table("contacts").delete().eq("lead_id", lead_id).execute()

    now = datetime.now(UTC).isoformat()
    rows = [
        {
            "lead_id":          lead_id,
            "buyer_type":       c.get("buyer_type"),
            "name":             c.get("name"),
            "title":            c.get("title"),
            "linkedin_url":     c.get("linkedin_url"),
            "relevance":        c.get("relevance"),
            "outreach_subject": c.get("outreach_subject"),
            "outreach_body":    c.get("outreach_body"),
            "created_at":       now,
        }
        for c in contacts
    ]
    client.table("contacts").insert(rows).execute()


def get_contacts_for_company(company: str) -> list[dict]:
    """
    Returns contacts already stored for any lead with this company name.
    Used by StakeholderAgent to avoid re-searching when the same company
    appears across multiple events.
    Returns empty list if no contacts found.
    """
    client = get_client()
    leads = (
        client.table("leads")
        .select("id")
        .eq("company", company)
        .execute()
    ).data

    if not leads:
        return []

    lead_ids = [l["id"] for l in leads]
    contacts = (
        client.table("contacts")
        .select("*")
        .in_("lead_id", lead_ids)
        .execute()
    ).data

    return _normalise_contacts(contacts)


def update_contact_outreach(contact_id: str, subject: str, body: str) -> None:
    """Update outreach fields on an existing contact row."""
    get_client().table("contacts").update({
        "outreach_subject": subject,
        "outreach_body":    body,
    }).eq("id", contact_id).execute()


# ─────────────────────────────────────────────────────────────
# Settings (integration API keys)
# ─────────────────────────────────────────────────────────────

def get_settings() -> dict:
    """Returns all settings as a key→value dict."""
    try:
        rows = get_client().table("settings").select("key, value").execute().data
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def save_setting(key: str, value: str) -> None:
    """Upserts a single setting by key."""
    get_client().table("settings").upsert(
        {"key": key, "value": value, "updated_at": datetime.now(UTC).isoformat()},
        on_conflict="key"
    ).execute()


def delete_setting(key: str) -> None:
    """Removes a setting (disconnect integration)."""
    get_client().table("settings").delete().eq("key", key).execute()


# ─────────────────────────────────────────────────────────────
# Convenience wrappers
# ─────────────────────────────────────────────────────────────

def save_lead(lead: dict) -> None:
    """Upserts the lead then replaces its contacts."""
    lead_id = upsert_lead(lead)
    insert_contacts(lead.get("contacts", []), lead_id)


def get_all_leads() -> list[dict]:
    """Returns all leads with contacts nested, ordered by icp_score desc."""
    client = get_client()
    leads = (
        client.table("leads")
        .select("*, contacts(*)")
        .order("icp_score", desc=True)
        .execute()
    ).data
    return leads


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _normalise_lead(row: dict) -> dict:
    """Convert a Supabase leads row back to the shape agents expect."""
    return {
        "id":                      row.get("id"),
        "company":                 row.get("company"),
        "division":                row.get("division"),
        "event_source":            row.get("event_source"),
        "discovery_confidence":    row.get("discovery_confidence"),
        "revenue_estimate":        row.get("revenue_estimate"),
        "icp_score":               row.get("icp_score", 0),
        "icp_breakdown": {
            "industry_fit":        row.get("industry_fit"),
            "revenue_tier":        row.get("revenue_tier"),
            "event_confirmation":  row.get("event_confirmation"),
            "product_overlap":     row.get("product_overlap"),
        },
        "qualification_rationale": row.get("qualification_rationale"),
        "contacts":                _normalise_contacts(row.get("contacts", [])),
    }


def _normalise_leads(rows: list[dict]) -> list[dict]:
    return [_normalise_lead(r) for r in rows]


def _normalise_contacts(contacts: list[dict]) -> list[dict]:
    return [
        {
            "id":               c.get("id"),
            "buyer_type":       c.get("buyer_type"),
            "name":             c.get("name"),
            "title":            c.get("title"),
            "linkedin_url":     c.get("linkedin_url"),
            "relevance":        c.get("relevance"),
            "outreach_subject": c.get("outreach_subject"),
            "outreach_body":    c.get("outreach_body"),
        }
        for c in contacts
    ]
