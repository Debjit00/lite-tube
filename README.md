# LiteTube

A lightweight, self-contained video sharing and streaming platform inspired by YouTube, built with **FastAPI**, **MySQL**, and **Vanilla HTML/CSS/JS**.

## Features

- **Home Feed & Discovery**: Responsive 16:9 dark-mode video grid, debounced search, category chips, channel filtering, and sorting (`Newest`, `Most Viewed`).
- **Watch Page & Range Streaming**: HTML5 `<video>` playback backed by HTTP `206 Partial Content` byte-range streaming for instant seeking, accurate play-triggered view counts, and an "Up Next" related sidebar.
- **Upload Studio**: Drag-and-drop MP4/WebM uploads with upload progress bar, automatic browser `<canvas>` 16:9 thumbnail capture & duration detection (plus optional custom thumbnail upload), and magic-byte validation.
- **Lightweight Authentication**: PBKDF2-HMAC-SHA256 password hashing with signed `HttpOnly` session cookies; guests can browse and watch freely while signed-in creators can upload and delete their own videos.
- **Cloud MySQL Backend**: Pooled `PyMySQL` connection management with automatic TLS/SSL support for cloud MySQL providers (`DATABASE_URL` or `MYSQL_*` variables in `.env`).
- **Zero-Config Seed Content**: Automatically creates `users` and `videos` tables and seeds 3 demo channels + 6 animated VP8 `.webm` sample clips on first run when the database is empty.

## Setup & Run

1. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Configure your cloud MySQL database:
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env` with either `DATABASE_URL` (e.g. `mysql://user:pass@host:port/dbname?ssl-mode=REQUIRED`) or `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_DATABASE`.

3. Start the server:
   ```powershell
   .\.venv\Scripts\uvicorn.exe app.main:app --reload
   ```

Open `http://127.0.0.1:8000` in your browser (or check `GET /api/health` to verify the MySQL connection).

### Demo Accounts (Pre-seeded)

| Username | Password | Channel |
| --- | --- | --- |
| `techbytes` | `demo1234` | TechBytes |
| `synthwave_lab` | `demo1234` | Synthwave Lab |
| `nature_loops` | `demo1234` | Nature Loops |

## Running Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
