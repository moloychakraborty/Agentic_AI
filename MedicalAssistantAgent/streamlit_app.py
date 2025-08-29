import os
import requests
import streamlit as st

st.set_page_config(page_title="Symptom Checker", page_icon="🩺", layout="centered")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/analyze")

st.title("🩺 Symptom Checker")
st.caption("Educational tool only — not a diagnosis. In an emergency, call your local emergency number.")

with st.form("intake"):
    col1, col2, col3 = st.columns(3)
    with col1:
        age = st.number_input("Age", min_value=0, max_value=120, value=30)
    with col2:
        sex = st.selectbox("Sex", ["female", "male", "other"], index=0)
    with col3:
        pregnant = st.checkbox("Pregnant?")

    symptoms_text = st.text_area(
        "Describe your symptoms",
        height=140,
        placeholder="e.g., tight chest pain radiating to left arm with shortness of breath for 2 hours",
    )

    col4, col5, col6 = st.columns(3)
    with col4:
        duration_hours = st.number_input("Duration (hours)", min_value=0.0, value=0.0, step=0.5)
    with col5:
        temp_c = st.number_input("Temp (°C)", min_value=0.0, value=0.0, step=0.1)
    with col6:
        hr_bpm = st.number_input("Heart rate (bpm)", min_value=0, value=0, step=1)

    spo2 = st.number_input("SpO₂ (%)", min_value=0, max_value=100, value=0, step=1, help="If you have a pulse oximeter")

    submitted = st.form_submit_button("Check symptoms")

if submitted:
    payload = {
        "age": int(age),
        "sex": sex,
        "pregnant": bool(pregnant),
        "symptoms_text": symptoms_text.strip(),
        "duration_hours": float(duration_hours) if duration_hours else None,
        "vitals": {
            "temp_c": float(temp_c) or None,
            "hr_bpm": int(hr_bpm) or None,
            "spo2": int(spo2) or None,
        },
        "conditions": [],
        "meds": [],
        "allergies": []
    }

    if not payload["symptoms_text"]:
        st.warning("Please enter your symptoms.")
    else:
        with st.spinner("Analyzing..."):
            try:
                r = requests.post(API_URL, json=payload, timeout=30)
                r.raise_for_status()
                result = r.json()
            except Exception as e:
                st.error(f"Couldn't reach the API at {API_URL}: {e}")
                result = None

        if result:
            triage = result.get("triage", {})
            level = triage.get("level", "UNKNOWN")
            reason = triage.get("reason", "")

            if level == "EMERGENCY":
                st.error("🚑 EMERGENCY — Seek urgent medical care now.")
            elif level == "URGENT":
                st.warning("⚠️ URGENT — Seek medical care within 24–48 hours.")
            elif level == "ROUTINE":
                st.info("ℹ️ ROUTINE — Clinic visit when convenient.")
            elif level == "SELF_CARE":
                st.success("✅ SELF-CARE — Home care guidance below.")

            st.write(f"**Triage:** {level}")
            if reason:
                st.caption(reason)

            sugg = result.get("llm_suggestions", {})
            st.subheader("Summary")
            st.write(sugg.get("summary", ""))

            colA, colB = st.columns(2)
            with colA:
                st.markdown("**What to do now**")
                for x in sugg.get("what_to_do_now", []):
                    st.markdown(f"- {x}")
            with colB:
                st.markdown("**What to avoid**")
                for x in sugg.get("what_to_avoid", []):
                    st.markdown(f"- {x}")

            st.markdown("**Monitoring signs**")
            for x in sugg.get("monitoring_signs", []):
                st.markdown(f"- {x}")

            st.markdown(f"**When to seek help:** {sugg.get('when_to_seek_help', '')}")

            st.divider()
            st.caption(sugg.get("disclaimer", "This tool is not a medical diagnosis or treatment."))

# Run locally: streamlit run c:/Users/Moloy/Project_AI/llms/MedicalAssistantAgent/streamlit_app.py
# Optionally set API_URL to override: API_URL=http://127.0.0.1:8000/analyze
