from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import os

# ----------------- Minimal symptom lexicon -----------------
SYMPTOM_LEXICON = {
    "29857009": ["chest pain", "pressure in chest", "tightness in chest"],
    "267036007": ["shortness of breath", "breathless", "dyspnea"],
    "25064002": ["headache", "severe headache", "worst headache"],
}

class Vitals(BaseModel):
    temp_c: Optional[float] = None
    hr_bpm: Optional[int] = None
    spo2: Optional[int] = None

class Intake(BaseModel):
    age: int = Field(ge=0, le=120)
    sex: str
    pregnant: Optional[bool] = None
    symptoms_text: str
    onset: Optional[datetime] = None
    duration_hours: Optional[float] = None
    conditions: List[str] = []
    meds: List[str] = []
    allergies: List[str] = []
    vitals: Optional[Vitals] = None

app = FastAPI(title="Symptom Checker API", version="0.1.0")

# CORS for local Streamlit (localhost:8501 → localhost:8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Symptom Normalization (very simplified) ----------
from rapidfuzz import process, fuzz

def normalize_symptoms(text: str):
    text = text.lower()
    candidates = []
    for code, phrases in SYMPTOM_LEXICON.items():
        best = process.extractOne(text, phrases, scorer=fuzz.partial_ratio)
        if best and best[1] >= 80:
            candidates.append({"label": best[0], "code": code})
    return candidates

# ---------- Red-flag rules ----------
def red_flags(norm, intake: Intake):
    labels = {n["label"] for n in norm}
    flags = []
    if {"chest pain", "shortness of breath"} <= labels:
        flags.append("Chest pain + dyspnea")
    if intake.vitals and intake.vitals.spo2 is not None and intake.vitals.spo2 < 92:
        flags.append("Low oxygen saturation (<92%)")
    if "severe headache" in labels and any(k in intake.symptoms_text.lower() for k in ["weakness", "slurred", "droop"]):
        flags.append("Severe headache + neuro deficits")
    if intake.pregnant and any(k in intake.symptoms_text.lower() for k in ["bleeding", "severe pain"]):
        flags.append("Pregnancy with concerning symptoms")
    return flags

# ---------- Triage logic ----------
class TriageLevel(str):
    EMERGENCY = "EMERGENCY"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"
    SELF_CARE = "SELF_CARE"

def triage(norm, flags, intake: Intake):
    if flags:
        return {"level": TriageLevel.EMERGENCY, "reason": "; ".join(flags)}
    if intake.age < 1 and (intake.vitals and intake.vitals.temp_c and intake.vitals.temp_c >= 38.0):
        return {"level": TriageLevel.URGENT, "reason": "Fever in infant"}
    if any(n["label"] == "shortness of breath" for n in norm):
        return {"level": TriageLevel.URGENT, "reason": "Breathlessness"}
    return {"level": TriageLevel.SELF_CARE, "reason": "No red flags detected"}

# ---------- LLM suggestions (safe fallback if no API key) ----------
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

GUARDRAIL_SYSTEM = (
    "You are a cautious medical information assistant. Output JSON only (valid minified json). "
    "Provide general self-care suggestions and when to seek care; do not diagnose or prescribe. "
    "Include a clear disclaimer. If emergency triage is indicated, reinforce seeking immediate help. "
    "Never provide dosages or medication names beyond OTC categories."
)

def llm_suggestions(payload: Dict[str, Any]):
    if not client:
        triage_level = payload.get("triage", {}).get("level", "SELF_CARE")
        if triage_level == "EMERGENCY":
            return {
                "summary": "Your symptoms may indicate a serious condition.",
                "what_to_do_now": ["Seek emergency care immediately."],
                "what_to_avoid": ["Do not drive yourself.", "Avoid eating or drinking until seen."],
                "monitoring_signs": ["Worsening chest pain", "Fainting"],
                "when_to_seek_help": "Now",
                "disclaimer": "This is general information, not medical advice."
            }
        else:
            return {
                "summary": "Your symptoms do not show urgent red flags.",
                "what_to_do_now": ["Rest", "Hydrate", "Consider over-the-counter pain relief if safe for you"],
                "what_to_avoid": ["Strenuous activity"],
                "monitoring_signs": ["New or worsening shortness of breath", "Chest discomfort"],
                "when_to_seek_help": "If symptoms persist or worsen",
                "disclaimer": "This is general information, not medical advice."
            }

    user_blocks = f"""
User demographics and symptoms:
- Age: {payload['intake'].age}
- Sex: {payload['intake'].sex}
- Pregnant: {payload['intake'].pregnant}
- Key normalized symptoms (SNOMED): {payload['normalized_symptoms']}
- Free-text: {payload['intake'].symptoms_text}
- Duration (hours): {payload['intake'].duration_hours}
- Comorbidities: {payload['intake'].conditions}
- Vitals: {payload['intake'].vitals.model_dump() if payload['intake'].vitals else {}}

Using the retrieved topics and sources: {payload['retrieved_sources']}

Return a json object with keys: summary, what_to_do_now, what_to_avoid, monitoring_signs, when_to_seek_help, disclaimer.
"""

    resp = client.chat.completions.create(
        model="gpt-5",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": GUARDRAIL_SYSTEM},
            {"role": "user", "content": user_blocks}
        ],
        temperature=0.2,
    )
    import json
    return json.loads(resp.choices[0].message.content)

# ---------- Simple source retrieval placeholder ----------
def retrieve_topics(norm):
    topics = []
    labels = [n["label"] for n in norm]
    if "chest pain" in labels:
        topics.append({"title": "Acute chest pain in adults", "url": ""})
    if "shortness of breath" in labels:
        topics.append({"title": "Dyspnea overview", "url": ""})
    return topics

@app.post("/analyze")
async def analyze(intake: Intake):
    norm = normalize_symptoms(intake.symptoms_text)
    flags = red_flags(norm, intake)
    triage_res = triage(norm, flags, intake)
    sources = retrieve_topics(norm)

    payload = {
        "intake": intake,
        "normalized_symptoms": norm,
        "red_flags": flags,
        "triage": triage_res,
        "retrieved_sources": sources,
    }
    suggestions = llm_suggestions(payload)

    return {
        **payload,
        "llm_suggestions": suggestions,
        "disclaimer": "This tool is not a medical diagnosis or treatment. If you think you're having a medical emergency, seek care immediately.",
    }

# Run locally: uvicorn app.main:app --reload --port 8000
