# Landscaping Quote Frontend — Step 3

Next.js frontend for the landscaping quote system.
Connects to the FastAPI backend from Steps 1 & 2.

---

## What's in this step

- Address autocomplete (Google Places API, gracefully degrades without a key)
- Job service selector (checkbox cards, loads from backend GET /jobs)
- Property size inputs with quick-select presets (small / average / large block)
- Optional modifiers: terrain, distance zone, access notes
- Animated loading state with progress steps
- Quote result card: price range, line item breakdown, summary, copy/email CTAs
- Fully connected to the Step 2 FastAPI backend

---

## Setup

### 1. Install dependencies
  cd landscaping-frontend
  npm install

### 2. Configure environment
  cp .env.local.example .env.local

Edit .env.local:

  NEXT_PUBLIC_API_URL=http://localhost:8000

  Optionally add your Google Maps key for address autocomplete:
  NEXT_PUBLIC_GOOGLE_MAPS_KEY=your_key_here

  To get a Google Maps key:
    - Go to https://console.cloud.google.com
    - Create a project, go to APIs and Services > Credentials
    - Create an API key, enable: Places API and Maps JavaScript API
    - Restrict the key to your domain in production

  The app works without this key — address field becomes a plain text input.

### 3. Start the backend (in a separate terminal)
  cd landscaping-quote
  uvicorn main:app --reload

### 4. Start the frontend
  npm run dev

Open http://localhost:3000

---

## File structure

  src/
  ├── app/
  │   ├── layout.tsx          Root layout, loads Google Maps script
  │   ├── page.tsx            Main quote page (form + loading + result)
  │   └── globals.css         Design tokens and global styles
  ├── components/
  │   ├── AddressAutocomplete.tsx   Google Places input
  │   ├── JobSelector.tsx           Service checkbox cards
  │   ├── PropertyInputs.tsx        m² inputs with size presets
  │   ├── QuoteCard.tsx             Quote result display
  │   └── QuoteLoading.tsx          Animated loading skeleton
  └── lib/
      └── api.ts                    Typed API client for the backend

---

## Design

Earthy, natural theme: deep greens, warm browns, off-white backgrounds.
Fonts: DM Serif Display (headings) + DM Sans (body).
All design tokens are CSS variables in globals.css — easy to retheme.

---

## Connecting Step 4 (Maps Vision — coming next)

When Step 4 is built, the property size inputs will be replaced with
auto-detected values. The frontend is already prepared for this:

In page.tsx, the condition_score is hardcoded at 0.4 with a comment:
  "Step 5 will compute this from weather/suburb data"

In PropertyInputs.tsx, an autoDetected prop already exists:
  <PropertyInputs autoDetected={true} values={detectedValues} />
  This switches the inputs to read-only and shows a satellite detection badge.

No other frontend changes needed for Steps 4 and 5.

---

## Production deployment

Build and deploy to Vercel (free):
  npm run build
  npx vercel

Set environment variables in Vercel dashboard:
  NEXT_PUBLIC_API_URL = your deployed FastAPI URL
  NEXT_PUBLIC_GOOGLE_MAPS_KEY = your key

Deploy the FastAPI backend to Railway, Render, or Fly.io (all have free tiers).
