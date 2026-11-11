import streamlit as st

from ui.api_client import ApiProblem
from ui.components import document_preview, job_progress, table
from ui.format import confidence_label, friendly_error, status_label
from ui.preview import pdf_first_page_png, pdf_page_count, preview_kind
from ui.state import api, call, header, require_login

u = require_login("upload")
header("Document Upload", "Invoices, purchase orders and goods-received notes (PDF/PNG/JPG) or a vendor-records CSV. The server validates every file again.")
MAX_MB, ALLOWED = 10, ["pdf", "png", "jpg", "jpeg", "csv"]
st.session_state.setdefault("uploader_n", 0)

file = st.file_uploader(f"Choose a file (max {MAX_MB} MB)", type=ALLOWED, key=f"uploader_{st.session_state['uploader_n']}")
if file is not None:
    data = file.getvalue()
    problems = []
    if len(data) == 0:
        problems.append("The file is empty.")
    if len(data) > MAX_MB * 1024 * 1024:
        problems.append(f"The file is larger than {MAX_MB} MB.")
    kind = preview_kind(file.name)
    if kind == "pdf" and not data.startswith(b"%PDF-"):
        problems.append("This does not look like a real PDF file.")
    for p in problems:
        st.error(p)
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(f"**{file.name}** · {len(data) / 1024:.1f} KB")
        if kind == "pdf" and not problems:
            png = pdf_first_page_png(data)
            st.image(png, caption=f"Preview, page 1 of {pdf_page_count(data) or '?'}") if png else st.warning("Preview not available; the server will still try to read the file.")
        elif kind == "image" and not problems:
            st.image(data, caption="Preview")
        elif kind == "csv" and not problems:
            st.code(data[:1500].decode("utf-8", "replace"))
    with c2:
        st.write("Ready to upload." if not problems else "Fix the problems on the left before uploading.")
        if st.button("Upload and process", type="primary", disabled=bool(problems)):
            try:
                with st.spinner("Uploading and validating..."):
                    res = api().upload("/api/documents", file.name, data, file.type or "application/octet-stream")
            except ApiProblem as e:
                st.error(friendly_error(e))
            else:
                if "imported" in res:
                    st.success(f"Vendor CSV processed: {res['imported']} imported, {res['skipped_existing']} already existed.")
                    if res["errors"]:
                        st.warning("Some rows were skipped:")
                        table(res["errors"])
                elif res.get("duplicate_upload"):
                    st.info(f"This exact file was uploaded before (document #{res['document_id']}). Nothing new was created.")
                    st.session_state["last_doc"] = res["document_id"]
                else:
                    st.session_state["last_doc"], st.session_state["last_job"] = res["document_id"], res["job_id"]
                    st.session_state["uploader_n"] += 1
                    st.rerun()

job_id, doc_id = st.session_state.get("last_job"), st.session_state.get("last_doc")
if doc_id:
    st.divider()
    st.subheader(f"Document #{doc_id}")
    if job_id:
        st.write("Processing runs in the background worker, so this page stays responsive.")
        job = job_progress(job_id)
        if job and job["status"] == "FAILED":
            st.error(f"Processing failed: {job['error'] or 'unknown error'}. Nothing was approved or paid.")
        elif job and job["status"] in ("QUEUED", "RUNNING", "RETRYING"):
            st.info("Still waiting. If this stays queued, check that the worker is running: `python -m backend.workers.worker`.")
        if st.button("Refresh status"):
            st.rerun()
    doc = call(api().get, f"/api/documents/{doc_id}")
    if doc:
        st.write(f"Type: **{doc['doc_type']}** · kind: **{doc['kind'] or '—'}** · status: **{doc['status']}**")
        if doc["fields"]:
            st.markdown("**Extraction results**")
            table([{"Field": f["name"], "Value": f["value"], "Confidence": confidence_label(f["confidence"], f["method"]), "Page": f["page"], "Source text": f["snippet"]} for f in doc["fields"]])
        if doc["invoice_id"]:
            inv = call(api().get, f"/api/invoices/{doc['invoice_id']}")
            if inv:
                st.write(f"Invoice record #{doc['invoice_id']}: {status_label(inv['invoice']['status'])}. Open **AI / Agent Workflow** to follow it.")
                for e in inv["exceptions"]:
                    if e["rule_id"].startswith("DOC_"):
                        st.warning(e["message"])
        with st.expander("Original document"):
            document_preview({"id": doc["id"], "filename": doc["filename"], "mime_type": doc["mime_type"]})

st.divider()
st.subheader("Recent uploads")
recent = call(api().get, "/api/documents", limit=15)
if recent:
    table([{"ID": d["id"], "File": d["filename"], "Type": d["doc_type"], "Status": d["status"], "Job": (d["job"] or {}).get("status"), "Invoice": d["invoice_id"], "Uploaded": d["created_at"]} for d in recent["items"]])
