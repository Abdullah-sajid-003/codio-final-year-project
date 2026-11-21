# Codio Backend

Python Flask REST API for the Codio AI-Powered Interactive Coding Education Platform.

## Project Structure

```
codio-backend/
├── run.py                          # Entry point — Flask app factory
├── config/
│   ├── settings.py                 # All env vars & constants (single source of truth)
│   └── logging.py                  # Logging configuration
├── app/
│   ├── models/
│   │   └── database.py             # CodioDatabase — SQLite schema & queries
│   ├── routes/                     # Flask Blueprints (one per domain)
│   │   ├── __init__.py             # Blueprint exports
│   │   ├── auth.py                 # POST /auth/signup, /auth/login, /auth/refresh
│   │   ├── video.py                # Video processing, status, frame analysis, playlists
│   │   ├── code.py                 # POST /code/execute, /code/complete
│   │   ├── user.py                 # User playlists & progress CRUD
│   │   └── quiz.py                 # Adaptive quiz session lifecycle
│   ├── services/                   # Business logic (no Flask dependency)
│   │   ├── pause_to_code.py        # PauseToCodeService orchestrator
│   │   ├── video_processing.py     # VideoProcessor — download, transcript, caching
│   │   ├── gemini_extractor.py     # GeminiCodeExtractor — Vision AI integration
│   │   ├── concept_detection.py    # ConceptDetector — AI concept analysis
│   │   ├── code_execution.py       # Piston proxy + local fallback + AI completion
│   │   └── quiz_service.py         # Quiz question generation & difficulty logic
│   └── utils/
│       ├── jwt_auth.py             # JWTManager + @token_required decorator
│       └── helpers.py              # sanitize_error_text, normalize_question_text
├── tests/                          # Test directory (pytest-ready)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Key Design Decisions

1. **Flask Blueprints** — Each domain (auth, video, code, user, quiz) is a separate Blueprint, making the codebase navigable and testable in isolation.

2. **Service Layer Pattern** — Business logic lives in `app/services/` with zero Flask imports. Services are injected into routes via `init_*_routes(db, service)` functions, enabling easy unit testing with mocks.

3. **Centralized Config** — All environment variables are loaded once in `config/settings.py`. No scattered `os.getenv()` calls throughout the codebase.

4. **Dependency Injection** — The `create_app()` factory in `run.py` creates shared `db` and `service` instances and passes them to route initializers, avoiding global state.

## Getting Started

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Set GEMINI_API_KEY, JWT_SECRET_KEY, ADMIN_INITIAL_PASSWORD, and YOUTUBE_API_KEY

# Run the server
python run.py
```

`YOUTUBE_API_KEY` is required for YouTube search and public video/playlist
metadata. Set it in the backend `.env` locally and in the Render backend
environment for deployment; do not commit the key. The Data API does not provide
video downloads, so media downloads still use yt-dlp and may be blocked by YouTube.
Transcript lookup tries `youtube-transcript-api` first, but that third-party
library is not the official Data API and may also be rate-limited or blocked.

`ADMIN_INITIAL_PASSWORD` is used only when creating the admin account in a new
database and must be at least 12 characters. It does not change an existing
admin password. To reset the existing local admin password, run this from
`codio-backend/`; the new password is entered through hidden terminal prompts:

```bash
python reset_admin_password.py
```

## Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/ -v --cov=app
```
