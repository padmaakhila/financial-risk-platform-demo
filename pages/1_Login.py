import streamlit as st

from ui.api_client import ApiProblem
from ui.format import friendly_error
from ui.state import header, sign_in, sign_out, user

header("Sign in", "Financial Document & Risk Analysis Platform (synthetic data only)")
u = user()
if u:
    st.success(f"Signed in as **{u['username']}** with role **{u['role']}**. Use the sidebar to open a page.")
    if st.button("Sign out"):
        sign_out()
        st.rerun()
else:
    with st.form("login_form"):
        username = st.text_input("Username", max_chars=64)
        password = st.text_input("Password", type="password", max_chars=200)
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if not username.strip() or not password:
            st.error("Enter both your username and your password.")
        else:
            try:
                sign_in(username.strip(), password)
                st.rerun()
            except ApiProblem as e:
                st.error(friendly_error(e))
    st.caption("Demo accounts (development only) are printed when you run `python -m scripts.seed_database`.")
with st.expander("What can each role do?"):
    st.markdown("- **admin**: everything, including users, settings and integrations\n- **reviewer**: review queue, approve / reject / request documents, release payments, import vendor CSV\n"
                "- **ap_clerk**: upload and process documents, view records (bank details masked)\n- **auditor**: read-only access to records, reports, audit trail and monitoring")
