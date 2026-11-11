import streamlit as st

from ui.components import table
from ui.state import api, call, header, require_login

require_login("admin")
header("Administration", "Users and roles, matching tolerances, and the mock integrations.")
tab_users, tab_settings, tab_int = st.tabs(["Users & roles", "Matching settings", "Integrations"])

with tab_users:
    res = call(api().get, "/api/admin/users")
    users = res["items"] if res else []
    table([{"ID": u["id"], "Username": u["username"], "Role": u["role"], "Active": u["is_active"], "Created": u["created_at"]} for u in users])
    st.markdown("**Create a user**")
    with st.form("create_user"):
        c = st.columns(3)
        name = c[0].text_input("Username (a-z, 0-9, . _ -)", max_chars=64)
        pw = c[1].text_input("Password (10+ characters, letters and digits)", type="password")
        role = c[2].selectbox("Role", ["ap_clerk", "reviewer", "auditor", "admin"])
        if st.form_submit_button("Create user", type="primary"):
            r = call(api().post, "/api/admin/users", {"username": name.strip(), "password": pw, "role": role})
            if r:
                st.success(f"User {r['username']} created.")
                st.rerun()
    if users:
        st.markdown("**Change a user**")
        with st.form("update_user"):
            target = st.selectbox("User", [u["id"] for u in users], format_func=lambda x: next(u["username"] for u in users if u["id"] == x))
            c = st.columns(3)
            new_role = c[0].selectbox("New role", ["(unchanged)", "ap_clerk", "reviewer", "auditor", "admin"])
            active = c[1].selectbox("Account", ["(unchanged)", "active", "disabled"])
            new_pw = c[2].text_input("New password (optional)", type="password")
            if st.form_submit_button("Save changes"):
                body = {}
                if new_role != "(unchanged)":
                    body["role"] = new_role
                if active != "(unchanged)":
                    body["is_active"] = active == "active"
                if new_pw:
                    body["password"] = new_pw
                if not body:
                    st.info("Nothing to change.")
                elif call(api().patch, f"/api/admin/users/{target}", body):
                    st.success("User updated.")
                    st.rerun()

with tab_settings:
    res = call(api().get, "/api/admin/settings")
    items = res["items"] if res else []
    if items:
        st.caption("These tolerances drive the deterministic matching rules. Changes apply to the next run and are written to the audit trail.")
        with st.form("settings_form"):
            new = {s["key"]: st.text_input(f"{s['key']}", value=s["value"], help=s["description"], key=f"set_{s['key']}") for s in items}
            if st.form_submit_button("Save settings", type="primary"):
                changed = {k: v.strip() for k, v in new.items() if v.strip() != next(s["value"] for s in items if s["key"] == k)}
                if not changed:
                    st.info("No changes.")
                else:
                    r = call(api().put, "/api/admin/settings", {"values": changed})
                    if r:
                        st.success("Saved: " + ", ".join(f"{k}: {v['old']} → {v['new']}" for k, v in r["updated"].items()))
    else:
        st.info("No settings found. Run `python -m scripts.init_db`.")

with tab_int:
    h = call(api().get, "/api/admin/integrations")
    if h:
        table([{"Component": "Database", "Healthy": h["database"]["healthy"], "Detail": ""},
               {"Component": "Mock ERP payments", "Healthy": h["erp_mock"]["healthy"], "Detail": h["erp_mock"]["url"]},
               {"Component": "Mock vendor verification", "Healthy": h["vendor_verification_mock"]["healthy"], "Detail": h["vendor_verification_mock"]["url"]},
               {"Component": "LLM provider", "Healthy": h["llm"]["available"], "Detail": f"{h['llm']['provider']} {h['llm']['model'] or ''}".strip()},
               {"Component": "Tesseract OCR", "Healthy": h["ocr"]["tesseract_available"], "Detail": "needed only for scanned documents"}])
        if not h["llm"]["available"]:
            st.caption("No LLM available: explanations use deterministic templates and the app works normally.")
    st.markdown("**Simulate an outage (mock services only)**")
    with st.form("simulate"):
        c = st.columns(3)
        which = c[0].selectbox("Service", ["erp", "vendor"])
        mode = c[1].selectbox("Mode", ["normal", "down", "timeout", "flaky", "reject_all"], help="reject_all applies to the vendor service only")
        fail_n = c[2].number_input("Failures before recovery (flaky)", 0, 10, 2)
        if st.form_submit_button("Apply"):
            r = call(api().post, f"/api/admin/integrations/{which}/simulate", {"mode": mode, "fail_n": int(fail_n)})
            if r:
                st.success(f"{which} service is now in mode '{r['mode']}'.")
