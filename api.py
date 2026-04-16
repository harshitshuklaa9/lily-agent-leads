import json
import logging
import os
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import get_all_leads, get_client, update_contact_outreach, get_settings, save_setting, delete_setting
from agents.outreach_agent import OutreachAgent

logger = logging.getLogger("api")

app = FastAPI()

# Allow localhost in dev and any deployed frontend origin
_frontend_url = os.environ.get("FRONTEND_URL", "*")
if _frontend_url == "*":
    _origins = ["*"]
else:
    _origins = ["http://localhost:5173", "http://localhost:3000", _frontend_url]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# Track pipeline run state
_pipeline_running = False
_pipeline_lock = threading.Lock()


@app.get("/leads")
def leads():
    return get_all_leads()


@app.post("/pipeline/run")
def run_pipeline():
    """
    Triggers the pipeline in a background thread.
    Returns immediately — poll /pipeline/status to track progress.
    """
    global _pipeline_running
    with _pipeline_lock:
        if _pipeline_running:
            return {"status": "already_running"}
        _pipeline_running = True

    def _run():
        global _pipeline_running
        try:
            import main as pipeline_main
            pipeline_main.main()
        except Exception as e:
            logger.error("Pipeline run failed: %s", e)
        finally:
            with _pipeline_lock:
                _pipeline_running = False

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "started"}


@app.get("/pipeline/status")
def pipeline_status():
    return {"running": _pipeline_running}


@app.post("/contacts/{contact_id}/outreach")
def generate_outreach(contact_id: str):
    """
    Generates outreach email for a single contact on demand.
    Returns cached version immediately if already generated.
    """
    client = get_client()

    # Load contact
    contact_rows = (
        client.table("contacts")
        .select("*")
        .eq("id", contact_id)
        .execute()
    ).data
    if not contact_rows:
        raise HTTPException(status_code=404, detail="Contact not found")
    contact_row = contact_rows[0]

    # Return cached if already generated — no LLM call needed
    if contact_row.get("outreach_subject") and contact_row.get("outreach_body"):
        return {
            "subject": contact_row["outreach_subject"],
            "body":    contact_row["outreach_body"],
            "cached":  True,
        }

    # Load the lead this contact belongs to
    lead_rows = (
        client.table("leads")
        .select("*")
        .eq("id", contact_row["lead_id"])
        .execute()
    ).data
    if not lead_rows:
        raise HTTPException(status_code=404, detail="Lead not found for contact")
    lead = lead_rows[0]

    # Build contact dict in the shape OutreachAgent expects
    contact = {
        "name":       contact_row.get("name"),
        "title":      contact_row.get("title"),
        "buyer_type": contact_row.get("buyer_type"),
        "relevance":  contact_row.get("relevance"),
    }

    # Generate email
    try:
        config = json.load(open("config.json"))
        agent = OutreachAgent(config)
        subject, body = agent._generate_email(lead, contact, config["icp"])
    except Exception as e:
        logger.error("Outreach generation failed for contact %s: %s", contact_id, e)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")

    # Cache result in DB
    update_contact_outreach(contact_id, subject, body)

    return {
        "subject": subject,
        "body":    body,
        "cached":  False,
    }


# ── Outreach edit ────────────────────────────────────────────────────────────

class OutreachUpdate(BaseModel):
    subject: str
    body: str

@app.patch("/contacts/{contact_id}/outreach")
def update_outreach(contact_id: str, payload: OutreachUpdate):
    """Saves manually edited outreach subject/body without regenerating."""
    client = get_client()
    rows = client.table("contacts").select("id").eq("id", contact_id).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Contact not found")
    update_contact_outreach(contact_id, payload.subject, payload.body)
    return {"status": "saved"}


# ── Integrations ─────────────────────────────────────────────────────────────

# Maps provider slug → settings key
PROVIDER_KEYS = {
    "linkedin_sales_nav": "linkedin_sales_nav_token",
    "clay":               "clay_api_key",
    "apollo":             "apollo_api_key",
}

class IntegrationPayload(BaseModel):
    provider: str
    api_key: str

@app.get("/integrations")
def get_integrations():
    """Returns which integrations are connected (boolean only — never returns actual keys)."""
    settings = get_settings()
    return {
        provider: bool(settings.get(key))
        for provider, key in PROVIDER_KEYS.items()
    }

@app.post("/integrations")
def connect_integration(payload: IntegrationPayload):
    """Saves an integration API key to the settings table."""
    key = PROVIDER_KEYS.get(payload.provider)
    if not key:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")
    if not payload.api_key.strip():
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    save_setting(key, payload.api_key.strip())
    return {"status": "connected", "provider": payload.provider}

@app.delete("/integrations/{provider}")
def disconnect_integration(provider: str):
    """Removes an integration API key."""
    key = PROVIDER_KEYS.get(provider)
    if not key:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    delete_setting(key)
    return {"status": "disconnected", "provider": provider}
