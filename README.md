# Smart Study — UPSC AI Study Portal

A local-first UPSC Prelims + Mains study portal with PDF ingestion, AI question generation, answer tracking, analytics, revision scheduling, and notes.

## Run locally
1. Install Python 3.10+.
2. Extract this ZIP and open a terminal in the folder.
3. Create and activate a virtual environment (recommended).
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`.
6. Export the environment variable before starting:
   - macOS/Linux: `export OPENAI_API_KEY="your_key"`
   - Windows PowerShell: `$env:OPENAI_API_KEY="your_key"`
7. Run: `uvicorn app:app --reload`
8. Open http://127.0.0.1:8000

## Notes / limitations
- PDF extraction uses selectable text. Scanned/image-only PDFs need OCR, which is not included yet.
- AI generation uses the OpenAI API and incurs API charges. Keep the key on the server; never put it in browser code.
- This is a single-user local prototype, not a production deployment. Add authentication, HTTPS, backups, rate limits, user isolation, and secure file lifecycle controls before public use.
- Mains questions are generated with a rubric; automatic examiner-quality marking is not yet enabled.
- UPSC-style questions are generated from the uploaded extract, not certified official PYQs. Verify facts against authoritative sources.
- SQLite database is stored in `smartstudy.db`; uploaded extracted text is stored in that local database.
