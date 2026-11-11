import streamlit as st

from ui.components import table
from ui.format import human_seconds, percent
from ui.state import api, call, header, require_login

require_login("monitoring")
header("Monitoring", "Job failures, workflow latency, AI availability and usage, API health, and audit-trail integrity. Secrets and bank details are never shown here.")
m = call(api().get, "/api/monitoring/metrics")
if m is None:
    st.stop()
j, ai, a = m["jobs"], m["ai"], m["api"]

st.subheader("Workflow jobs")
c = st.columns(6)
c[0].metric("Total jobs", j["total"])
c[1].metric("Succeeded", j["succeeded"])
c[2].metric("Failed", j["failed"])
c[3].metric("Error rate", percent(j["failure_rate"]))
c[4].metric("Latency p50", human_seconds(j["latency_p50_s"]))
c[5].metric("Latency p95", human_seconds(j["latency_p95_s"]))
st.caption(f"Queued or running: {j['queued_or_running']} · jobs that needed a retry: {j['retried_jobs']}")
st.markdown("**Recent failures and retries**")
table([{"Job": f["job_id"], "Type": f["type"], "Status": f["status"], "Error": f["error_class"], "Message": f["message"], "Attempts": f["attempts"], "Invoice": f["invoice_id"]} for f in m["failures"]])

st.subheader("AI usage and availability")
c = st.columns(5)
c[0].metric("Model calls", ai["model_calls"])
c[1].metric("Template fallbacks", ai["template_fallbacks"])
c[2].metric("Fallback rate", percent(ai["fallback_rate"]))
c[3].metric("Tokens", f"{ai['prompt_tokens']} in / {ai['completion_tokens']} out")
c[4].metric("Model latency p95", f"{ai['model_latency_p95_ms']} ms" if ai["model_latency_p95_ms"] is not None else "—")
st.caption(f"Cost: {ai['cost_usd'] or 'not reported by the provider'}" + (f" ({ai['cost_note']})" if ai["cost_note"] else ""))

st.subheader("API")
c = st.columns(4)
c[0].metric("Requests (recent)", a["requests"])
c[1].metric("Server error rate", percent(a["server_error_rate"]))
c[2].metric("p50 / p95", f"{a['p50_ms'] or '—'} / {a['p95_ms'] or '—'} ms")
c[3].metric("Client errors (4xx)", a["client_errors"])

if m["integrations"]:
    st.subheader("Integration health")
    h = m["integrations"]
    table([{"Component": "Database", "Healthy": h["database"]["healthy"]}, {"Component": "ERP mock", "Healthy": h["erp_mock"]["healthy"]},
           {"Component": "Vendor verification mock", "Healthy": h["vendor_verification_mock"]["healthy"]}, {"Component": f"LLM ({h['llm']['provider']})", "Healthy": h["llm"]["available"]},
           {"Component": "Tesseract OCR", "Healthy": h["ocr"]["tesseract_available"]}])

st.subheader("Audit trail integrity")
if st.button("Verify audit hash chain"):
    v = call(api().get, "/api/audit/verify", quiet=("FORBIDDEN",))
    if v:
        (st.success if v["chain_ok"] else st.error)(f"{v['events']} events checked. " + ("Chain intact." if v["chain_ok"] else f"First broken event: #{v['first_bad_event_id']}."))
        st.caption(v["note"])
