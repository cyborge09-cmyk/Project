# Chess Board PM

A project management board built on a chess metaphor: **every square is a project, every piece is a person.**
The 8×8 grid shows the whole portfolio at once — project status by colour, team composition by the pieces
standing on each square — and people are reassigned by dragging their piece from one square to another.

Python (FastAPI) on **Vercel**, data and auth on **Supabase**.

| Piece | Role | Piece | Role |
|---|---|---|---|
| ♚ King | Project lead | ♝ Bishop | Designer / architect |
| ♛ Queen | Tech lead | ♞ Knight | Specialist |
| ♜ Rook | Senior developer | ♟ Pawn | Junior / support |

One king and one queen per project, enforced both in the API and by a partial unique index in Postgres.

## What it does

- **Board** — 2×2 to 16×16 grid, a project per square, status colour wash and a progress bar on each square.
- **Projects** — create, edit, move between squares (drag), delete; status, progress, dates, tags, blockers.
- **People** — assign by dragging from the team roster onto a square, change a person's piece, drag a piece
  between squares to reassign, remove from a project. The roster shows how many in-flight projects each person is on.
- **Filters** — status chips, per-person filter, and full text search over names, descriptions, tags and people.
  Non-matching squares dim rather than disappear, so the board's spatial layout is preserved.
- **Project drawer** — details, team with role selectors, dependencies, comments, activity.
- **Analytics** — board fill, average progress, completion rate, status breakdown, at-risk projects
  (blocked or due within a week), and a resource-allocation table flagging anyone on more than three
  in-flight projects or carrying more than 40 allocated hours.
- **My work** — every square the signed-in person's piece stands on, with their own load.
- Light/dark themes, keyboard-reachable squares, ARIA labels on every square and piece, responsive down to phones.

## Layout

```
api/index.py          Vercel entrypoint (exports the ASGI app)
app/main.py           FastAPI app, middleware, error handling
app/config.py         env-driven settings
app/supabase.py       thin async PostgREST + GoTrue clients
app/session.py        signed session cookie holding the Supabase tokens
app/deps.py           auth dependencies (incl. transparent token refresh)
app/models.py         request schemas + the piece/status vocabulary
app/service.py        shared queries and the analytics calculations
app/routers/          auth, boards, projects, me, pages
app/templates/        Jinja2 pages
app/static/           CSS and vanilla JS (no build step)
supabase/schema.sql   tables, triggers, RLS policies
tests/                pytest suite (Supabase mocked with respx)
```

Every database call is made with the **caller's** JWT, so the row level security policies in
`supabase/schema.sql` — not the application — are what actually enforce who can see and change what.
The service role key is never used and never needs to be deployed.

## Setup

### 1. Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. Open the SQL editor and run the whole of `supabase/schema.sql`.
3. Under **Authentication → Providers**, keep email/password enabled. For a quick start, turn off
   "Confirm email" so new accounts get a session immediately (the app handles either setting).
4. Copy the project URL and the **anon** key from **Project Settings → API**.

### 2. Run it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # fill in SUPABASE_URL, SUPABASE_ANON_KEY, SESSION_SECRET
./run.sh                      # http://127.0.0.1:8000
```

Sign up, create a board, and click any square to add a project.

### 3. Deploy to Vercel

```bash
npm i -g vercel
vercel                        # link the project
vercel env add SUPABASE_URL
vercel env add SUPABASE_ANON_KEY
vercel env add SESSION_SECRET # python -c "import secrets; print(secrets.token_hex(32))"
vercel --prod
```

`vercel.json` routes every request to `api/index.py` and ships `app/**` (templates and static assets)
with the function. Importing the repo in the Vercel dashboard works the same way — set the three
environment variables under **Settings → Environment Variables**.

### Environment variables

| Name | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | yes | `https://<project>.supabase.co` |
| `SUPABASE_ANON_KEY` | yes | anon/publishable key; the service role key is not used |
| `SESSION_SECRET` | yes | signs the session cookie — changing it signs everyone out |
| `COOKIE_SECURE` | no | defaults to true on Vercel, false locally |
| `SESSION_MAX_AGE` | no | cookie lifetime in seconds (default 7 days) |

Without `SUPABASE_URL`/`SUPABASE_ANON_KEY` the app still boots and serves a setup page explaining what is missing.

## API

Interactive docs at `/api/docs`. Everything below is cookie-authenticated.

```
POST   /api/auth/signup|login|logout
GET    /api/boards                          POST /api/boards
GET    /api/boards/{id}                     PATCH/DELETE /api/boards/{id}
GET    /api/boards/{id}/people              POST /api/boards/{id}/people
GET    /api/boards/{id}/activity            GET  /api/boards/{id}/analytics
POST   /api/boards/{id}/projects
GET    /api/projects/{id}                   PATCH/DELETE /api/projects/{id}
POST   /api/projects/{id}/members           PATCH/DELETE /api/projects/{id}/members/{member_id}
POST   /api/projects/{id}/members/{member_id}/move   # drag a piece to another square
POST   /api/projects/{id}/comments
POST   /api/projects/{id}/dependencies/{depends_on_id}
GET    /api/me                              GET /api/me/workload
```

## Tests

```bash
pytest
```

The suite covers the analytics calculations and the HTTP routes end to end, with Supabase's REST API
mocked by `respx` — no network and no Supabase project required.

## Roadmap

This is Phase 1 of the project plan plus the parts of Phase 2/3 that the board makes immediately useful
(drag & drop, search and filtering, workload, comments, activity, analytics). Still open from the plan:
WebSocket live collaboration, Slack/Teams/Jira integrations, PDF export, burndown and velocity charts,
board templates and multi-board portfolio rollups.
