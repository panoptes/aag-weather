# PANOPTES AAG Weather — Development Guidelines

Audience: Advanced developers contributing to this repository. This document captures project-specific knowledge to accelerate setup, testing, and debugging.


## 1) Build and Configuration

- Runtime
  - Python: 3.12+.
  - Platforms: Linux is the primary target. macOS generally works for development, but hardware integration is Linux-centric.

- Build system and tooling (Hatch)
  - We use Hatch for builds and local dev tooling. Versioning is VCS-based via hatch-vcs.
  - All configuration is centralized in pyproject.toml.
  - Install Hatch (once per machine):
    - pip install -U hatch
  - Build a wheel/sdist:
    - hatch build
  - Show/respect version: derived from Git tags; fallback is "unknown" in editable checkouts.

- Development install (recommended)
  - Create/activate a virtual environment, then install the package with testing extras:
    - pip install -e '.[testing]'
  - Notes:
    - Extras: `testing` installs pytest and coverage plugins used by our config.
    - Some optional extras listed by transitive deps may warn (e.g., typer[all]); these warnings are harmless for local dev.
  - You can also use Hatch to run tests without globally installing pytest in your venv (see Testing below).

- Entry points / CLI
  - Console script: `aag-weather` → `aag.cli:app` (Typer application).
  - Typical commands:
    - `aag-weather serve` — start the FastAPI service (defaults: host 127.0.0.1, port 8080 unless overridden).
    - `aag-weather capture` — read from the AAG CloudWatcher and write periodic readings to a file (CSV/JSON depending on output file extension).

- Web service
  - The service is implemented with FastAPI (and fastapi-utils). The `serve` subcommand runs the ASGI app.
  - For local development, you can query `GET /weather` (e.g., `http :8080/weather`) once the service is running.

- Configuration model
  - Settings are defined via Pydantic (`aag.settings.WeatherSettings`).
  - Configuration can be provided by environment variables or a local `config.env` in the working directory. Environment variables are prefixed with `AAG_`.
  - Nested settings (e.g., thresholds, heater) use double underscores: `AAG_THRESHOLDS__CLOUDY`, `AAG_HEATER__MIN_POWER`, etc. See README’s configuration table for full list and defaults.
  - Serial device default: `/dev/ttyUSB0`. For testing, `loop://` can be used as a non-hardware serial URI.

- Linting and formatting (Ruff)
  - Ruff is used for linting and formatting; configuration lives in pyproject.toml.
  - Style: Google-style docstrings via pydocstyle (configured through Ruff).
  - Common commands:
    - ruff check .
    - ruff format .


## 2) Testing

- Test runner and configuration
  - Pytest settings are in pyproject.toml under `[tool.pytest.ini_options]`.
  - Important defaults:
    - Coverage: `--cov aag`, `--cov-report term-missing`, `--cov-report xml:build/coverage.xml`.
    - Doctests are enabled: `--doctest-modules`.
    - Verbosity: `-vv -ra`.
    - Strict markers are enabled.
    - Tests are discovered in `tests/`.

- Installing test dependencies
  - Easiest: `pip install -e '.[testing]'`.
  - Alternatively, use Hatch’s test env (isolated): Hatch will provision pytest based on `[tool.hatch.envs.test]`.

- Running tests
  - With Hatch (recommended for hermetic runs):
    - hatch run test           # runs pytest with configured defaults
    - hatch run test -- -q     # pass extra args to pytest
  - Directly with pytest (if installed):
    - pytest
    - pytest tests/test_weather.py -q
    - pytest tests/test_weather.py::test_get_safe_reading -q
  - Coverage XML will be written to `build/coverage.xml`.

- Doctests
  - Doctests run against all modules due to `--doctest-modules`. When adding docstrings with examples, keep in mind the configured flags: `ELLIPSIS`, `NORMALIZE_WHITESPACE`, `ALLOW_UNICODE`, `IGNORE_EXCEPTION_DETAIL`.

- Pytest example (verified)
  - Minimal smoke test example:

    File: `tests/test_demo_guidelines.py`
    
    def test_import_and_version():
        import aag
        assert isinstance(aag.__version__, str)
        assert len(aag.__version__) >= 0

  - Run only this test: `pytest tests/test_demo_guidelines.py -q`.

- Known warnings
  - Pydantic v2 deprecation warnings about class-based `config` may appear during tests; they are benign for now.
  - In `tests/test_weather.py::test_bad_port`, pytest may report an unraisable exception from `CloudSensor.__del__` when the sensor fails to initialize. This is known and harmless in tests; avoid relying on destructor side effects.

- Tox
  - Tox is no longer used in this project (tox.ini was removed). Prefer Hatch envs or run pytest directly.


## 3) Additional Development Information

- Source layout and packaging
  - `src/` layout; top-level package is `aag`.
  - Versioning managed by `hatch-vcs` (see `pyproject.toml`). In editable checkouts without build metadata, `aag.__version__` may be `'unknown'`.

- Code style and linting
  - Use Ruff for linting/formatting. Black/Flake8 are not required here.
  - Config highlights (see pyproject):
    - Line length: 100; `E203, W503` ignored.
    - Docstrings: Google convention.

- Type hints
  - The codebase uses type hints in places but does not enforce mypy in CI by default. Adding annotations is encouraged for new/changed code.

- FastAPI and CLI conventions
  - CLI built with Typer; keep subcommands cohesive and documented via `--help`.
  - When adding endpoints to the FastAPI server, document them in README and consider adding simple HTTP-based tests using httpx/anyio if functionality grows.

- Hardware/serial development notes
  - For development without hardware, use `serial_port='loop://'` or set `AAG_SERIAL_PORT=loop://` to avoid opening a real device. Connecting will return False under tests; use `raise_exceptions=False` to suppress exceptions.
  - Real deployments must ensure appropriate permissions to read `/dev/ttyUSB*`.

- Troubleshooting
  - ImportError: `No module named 'aag'` when running pytest → ensure `pip install -e '.[testing]'` or set `PYTHONPATH=src`.
  - Missing deps (e.g., `pydantic-settings`) → install testing extras as above or run `pip install -e .` to pull runtime deps.
  - Port issues on macOS/Windows → configure `AAG_SERIAL_PORT` accordingly or use `loop://` for dev.
  - Coverage "No data to report" → usually happens if imports fail before tests run; fix imports/deps first.


## 4) Quick Start (validated)

1) Create venv and install (editable):
   - python -m venv .venv && source .venv/bin/activate
   - pip install -U pip setuptools wheel
   - pip install -e '.[testing]'

2) Run tests:
   - hatch run test           # preferred isolated run
   - pytest -q                # if pytest is installed in your venv

3) Try the service locally:
   - aag-weather serve
   - http :8080/weather

4) Simulate capture (no hardware):
   - AAG_SERIAL_PORT=loop:// aag-weather capture --output-file weather.json

5) Build artifacts (optional):
   - pip install hatch
   - hatch build

Keep temporary/demo files out of commits. Only documentation changes should persist unless implementing a feature or fix.
