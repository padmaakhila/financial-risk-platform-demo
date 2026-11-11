"""Read-only AI Copilot add-on for the Financial Risk Platform.

Nothing is imported eagerly so that importing ``ap_copilot`` never pulls in
FastAPI / Streamlit / SQLAlchemy unless the relevant submodule is used.
"""
__all__ = ["router", "streamlit_widget"]
