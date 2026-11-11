# Windows setup, step by step (beginner)

Everything below uses **PowerShell** inside **VS Code**. Nothing needs admin rights except the optional installers.

## 0. Install once
1. **Python 3.11 or newer** (3.12 also worked in testing): https://www.python.org/downloads/ . In the installer tick **"Add python.exe to PATH"**.
2. **VS Code**: https://code.visualstudio.com/ . Extensions: *Python* (Microsoft), *SQLite Viewer* (to browse `data\app.db`), *Markdown Preview Mermaid Support* (to see the diagrams).
3. Optional: **Tesseract OCR** (only for scanned documents) and **Ollama** (only for AI explanations). Both are described at the end; the app works without them.

> About SSMS: SQL Server Management Studio is only a *viewer/manager*. It is not a database engine, and this project does not need it. SQLite (a single file) is the default database. See `docs/SQLSERVER_SETUP.md` if you want SQL Server Express later.

## 1. Open the project
VS Code > File > Open Folder > the `financial-risk-platform` folder > Terminal > New Terminal (make sure it says PowerShell).

## 2. Create the virtual environment and install packages
```powershell
py -3.11 -m venv .venv          # if this fails: py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1    # prompt should start with (.venv)
python -m pip install --upgrade pip
pip install -r requirements.txt
```
If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer Y, activate again.

## 3. Configure
```powershell
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
Open `.env` and paste the printed text after `SECRET_KEY=`. Never share or commit `.env`.

## 4. Create the database and the synthetic data
```powershell
python -m scripts.init_db            # tables + default settings (data\app.db)
python -m scripts.seed_database      # 520 invoices, POs, GRNs, ground truth; prints demo logins
python -m scripts.generate_documents # sample PDFs in data\documents
python -m scripts.make_demo_documents   # files for the demo in data\demo
python -m pytest -q                  # run the tests (takes a few minutes the first time)
```
Reset later with `python -m scripts.reset_database --yes` (makes a backup first).

## 5. Start the five processes
Open five terminals (Terminal > Split Terminal), activate `.venv` in each, then run one command per terminal:
```powershell
uvicorn backend.integrations.erp_mock_app:app --port 8101        # 1 mock ERP
uvicorn backend.integrations.vendor_mock_app:app --port 8102     # 2 mock vendor verification
uvicorn backend.main:create_app --factory --port 8000            # 3 API  (docs: http://localhost:8000/docs)
python -m backend.workers.worker                                 # 4 worker (extraction + workflow)
streamlit run app.py                                             # 5 web app: http://localhost:8501
```
Sign in with a demo account printed by the seed script (for example the reviewer). Stop any process with Ctrl+C.

## 6. Optional: Tesseract OCR (scanned documents)
Install the Windows build of Tesseract (for example the UB Mannheim installer). Then either add its folder to PATH or set in `.env`:
`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`. Check with `tesseract --version`. Without it, scans are marked "needs manual entry" with a clear message.

## 7. Optional: Ollama (AI explanations on an 8 GB laptop)
Install Ollama for Windows, then:
```powershell
ollama pull qwen2.5:1.5b        # about 1 GB; llama3.2:3b is about 2 GB and slower
```
Keep `LLM_PROVIDER=ollama` and `OLLAMA_MODEL=qwen2.5:1.5b` in `.env`. Expect 10-60 seconds per explanation on CPU. If answers time out, raise `LLM_TIMEOUT_SECONDS` (for example 90). Close browser tabs/other apps for memory. If Ollama is not running, the app simply uses template explanations and says so.
An external AI API stays **off** unless you set `LLM_API_ENABLED=true` plus URL, key and model; it would send redacted text to a third party and may cost money.

## 8. Daily workflow
Activate `.venv`, start the five processes, work, stop with Ctrl+C. The database is the file `data\app.db`; back it up by copying it while the app is stopped.
