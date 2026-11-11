"""Streamlit entry point. Run:  streamlit run app.py
Navigation is role-aware (a convenience); the FastAPI backend enforces permissions on every request."""
import streamlit as st
from ui.theme import apply_theme
from ap_copilot.streamlit_widget import (
    render_copilot,
    clear_copilot_state
)
st.set_page_config(page_title="AP Risk Platform", page_icon="🧾", layout="wide")
apply_theme()
from backend.auth.permissions import can  # noqa: E402
from ui.state import sign_out, user  # noqa: E402

PAGES = [("pages/2_Dashboard.py", "Dashboard", "📊", "view_reports"), ("pages/3_Document_Upload.py", "Document Upload", "📤", "upload"),
         ("pages/4_Business_Records.py", "Business Records", "🗂️", "view_records"), ("pages/5_Agent_Workflow.py", "AI / Agent Workflow",  "🧠", "view_records"),
         ("pages/6_Review_Queue.py", "Review & Approval", "✅", "view_queue"), ("pages/7_Reports.py", "Reports", "📑", "view_reports"),
         ("pages/8_Administration.py", "Administration", "⚙️", "admin"), ("pages/9_Monitoring.py", "Monitoring", "📈", "monitoring")]

u = user()
allowed = [(p, t, i) for p, t, i, perm in PAGES if u and can(u["role"], perm)]
pages = [st.Page("pages/1_Login.py", title="Sign in" if not u else "Account", icon="🔐", default=not allowed)]
pages += [st.Page(p, title=t, icon=i, default=(n == 0)) for n, (p, t, i) in enumerate(allowed)]
nav = st.navigation(pages)

with st.sidebar:
    st.markdown("### 🧾 AP Risk Platform")
    st.caption("Synthetic data only")
    if u:
        st.write(f"**{u['username']}** · {u['role']}")
        if st.button("Sign out", key="sidebar_signout"):
            sign_out()
            st.rerun()
if u:
    render_copilot()
else:
    clear_copilot_state()

nav.run()
