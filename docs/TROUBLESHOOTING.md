# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `py` or `python` is not recognised | Python not on PATH | Reinstall Python and tick "Add python.exe to PATH", reopen the terminal |
| `Activate.ps1 cannot be loaded` | PowerShell script policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `pip install` fails building a package | Old pip or unsupported Python | `python -m pip install --upgrade pip`; use Python 3.11 or 3.12 64-bit |
| `ModuleNotFoundError: backend` | Running from the wrong folder | `cd` to the project root (where `app.py` is); use `python -m ...` commands exactly as written |
| `RuntimeError: SECRET_KEY must be set` | `APP_ENV=production` with the default key | Put a random 32+ character `SECRET_KEY` in `.env` |
| Streamlit shows "Cannot reach the API" | API not running or wrong `BACKEND_URL` | Start the API window; check `BACKEND_URL` in `.env` |
| Login says incorrect username or password | Wrong demo password or DB not seeded | Re-run `python -m scripts.seed_database` (fresh DB: `reset_database --yes`); passwords are printed by the seed script |
| "Too many failed sign-in attempts" | Lockout (5 failures) | Wait 5 minutes or restart the API |
| Upload stays "Queued" | Worker not running | Start `python -m backend.workers.worker` |
| Job FAILED with `OperationalError` / "database is locked" | Two writers on SQLite | Run only one worker; stop other tools that have `app.db` open for writing |
| Scanned file says "needs manual entry" | Tesseract missing or scan unreadable | Install Tesseract (see WINDOWS_SETUP) or upload a clearer scan |
| Explanations say "Template-generated" | No LLM, timeout, or verification rejected the model | Expected behaviour. Check Ollama is running; raise `LLM_TIMEOUT_SECONDS`; see Monitoring page for the fallback reason |
| Ollama is very slow / out of memory | 8 GB RAM, CPU only | Use `qwen2.5:1.5b`, close other apps, raise the timeout, or accept templates |
| Payment shows "pending" | ERP mock is down or in outage mode | Start the ERP mock; Administration > Integrations > mode `normal`; press **Release payment** again (safe to repeat) |
| "Port already in use" | A previous process is still running | Close that terminal or use another `--port` and update `.env` |
| `pytest` failures mentioning Tesseract | Real-OCR tests need Tesseract | They are skipped automatically when it is missing; install it to run them |
| Browser shows a blank/old Streamlit page | Cached session | Hard refresh (Ctrl+F5) or restart `streamlit run app.py` |
| Antivirus quarantines `data\documents\*.exe` | The unsupported-file sample is a fake "MZ" file | Expected; it is harmless test content. Delete it or add an exclusion for `data\` |

Still stuck? Copy the **last 20 lines** of the failing terminal (they contain no passwords; logs scrub secrets) and the exact command you ran.
