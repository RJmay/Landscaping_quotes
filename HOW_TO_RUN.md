# How to Run the Landscaping Quote System

Two terminals required — one for the backend, one for the frontend.
Everything below assumes you are on Mac/Linux. Windows commands are noted where different.

---

## Prerequisites — do this once

### 1. Install Python dependencies (backend)
Open a terminal, navigate to the backend folder:

    cd landscaping-quote
    pip install -r requirements.txt

This installs: fastapi, uvicorn, anthropic, sqlalchemy, asyncpg, httpx, redis, python-dotenv

### 2. Install Node dependencies (frontend)
Open a second terminal, navigate to the frontend folder:

    cd landscaping-frontend
    npm install

### 3. Create your .env files

Backend — create landscaping-quote/.env:

    ANTHROPIC_API_KEY=sk-ant-your-key-here
    DATABASE_URL=postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres
    GOOGLE_MAPS_API_KEY=your_google_maps_key_here     # Optional — Step 4
    REDIS_URL=redis://localhost:6379/0                 # Optional — caching

Frontend — create landscaping-frontend/.env.local:

    NEXT_PUBLIC_API_URL=http://localhost:8000
    NEXT_PUBLIC_GOOGLE_MAPS_KEY=your_google_maps_key_here   # Optional

### 4. Set up the database (once, or after schema changes)

In the backend terminal:

    cd landscaping-quote
    python seed_db.py

You should see:
    ✓ Tables created (or already exist)
    ✓ Seeded 6 job rates
    ✓ Seeded 13 suburb profiles
    ✓ Database setup complete.

---

## Running the system

### Terminal 1 — Backend (FastAPI)

    cd landscaping-quote
    uvicorn main:app --reload --port 8000

You should see:
    INFO:     Started server process
    INFO:     Waiting for application startup.
    INFO:     Application startup complete.
    INFO:     Uvicorn running on http://127.0.0.1:8000

The --reload flag means the server restarts automatically when you edit Python files.
Leave this terminal running.

### Terminal 2 — Frontend (Next.js)

    cd landscaping-frontend
    npm run dev

You should see:
    ▲ Next.js 14.2.3
    - Local:   http://localhost:3000
    - Network: http://192.168.x.x:3000

Leave this terminal running.

### Open in browser

    http://localhost:3000     ← The quote form (main app)
    http://localhost:8000/docs   ← Backend API docs (auto-generated, great for testing)

---

## Testing each step independently

### Test Step 1 — Pricing core (no database needed)

    cd landscaping-quote
    python test_quote.py

Runs 3 test quotes with hardcoded property data and prints the results.
Does NOT require a database or Google Maps key.

### Test Step 4 — Satellite area detection

    cd landscaping-quote
    python test_maps_agent.py

Requires ANTHROPIC_API_KEY and GOOGLE_MAPS_API_KEY.
Without Maps key, it tests the fallback path (still works).

### Test Step 5 — Condition scoring (NEW)

    cd landscaping-quote
    python test_condition_agent.py

No API keys needed at all — Open-Meteo is free and keyless.
Shows per-job condition scores and the weather context string for several Brisbane suburbs.

### Test the /condition endpoint via browser

Once the backend is running:

    http://localhost:8000/condition?address=42+Eucalyptus+Drive&suburb=Calamvale&state=QLD&job_ids=lawn_mowing,gutter_cleaning

Returns JSON showing the live condition score computed from real weather data.

---

## What each terminal shows

### Backend terminal (uvicorn)
Every API request is logged here:
    INFO: 127.0.0.1:52341 - "POST /quote HTTP/1.1" 200 OK
    INFO: 127.0.0.1:52342 - "GET /analyse-property HTTP/1.1" 200 OK

Errors and warnings also appear here — this is where to look if something breaks.

### Frontend terminal (Next.js)
Hot-reload notifications when you edit frontend files:
    event - compiled client and server successfully in 234ms

---

## Common issues

### "Connection refused" on the frontend
The backend isn't running. Start Terminal 1 first.

### "DATABASE_URL environment variable is not set"
You have not created landscaping-quote/.env or it is missing the DATABASE_URL line.

### "Could not load services. Is the backend running?"
The frontend cannot reach http://localhost:8000. Check Terminal 1.

### Satellite analysis returns fallback estimates
GOOGLE_MAPS_API_KEY is not set, or the address could not be geocoded.
The app still works — property sizes fall back to manual input.

### Condition score is always 0.4
The condition agent failed silently. Check the backend terminal for warnings.
Run python test_condition_agent.py to test the weather API independently.

### Windows users
Replace export with set in Command Prompt, or use PowerShell:
    $env:ANTHROPIC_API_KEY="sk-ant-..."
Or use a .env file — python-dotenv loads it automatically.

---

## Full pipeline sequence (what happens when a user submits a quote)

1. User enters address → frontend calls GET /analyse-property
2. Backend geocodes address → fetches satellite PNG → Claude vision analyses it
3. Returns lawn/roof/gutter/driveway measurements → frontend pre-fills inputs
4. User selects services → clicks "Get my instant quote"
5. Frontend calls POST /quote with all measurements + job IDs
6. Backend:
   a. Loads job rates from database
   b. Geocodes suburb → fetches 60 days of weather from Open-Meteo
   c. Combines weather + suburb profile → per-job condition scores (Step 5)
   d. Builds structured pricing prompt with all data substituted in
   e. Calls Claude Sonnet → gets JSON price range
   f. Saves quote to database with quote_id
   g. Returns quote to frontend
7. Frontend displays price range, line items, summary, and CTA

Total time: approximately 8–14 seconds end to end.
  Steps 1–3 (satellite): 4–6 seconds
  Steps 5–7 (condition + pricing): 4–8 seconds

---

## Current system status

  Step 1  Pricing core            DONE
  Step 2  Database layer          DONE
  Step 3  Frontend                DONE
  Step 4  Satellite area detection DONE
  Step 5  Condition scoring       DONE  (this step)
  Step 6  Caching, auth, booking  Next
