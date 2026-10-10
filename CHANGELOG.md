# Changelog

All notable changes to the **AI Test Case Generator** extension are documented here.

## [0.4.0] - 2026-10-06

### Added
- **Run Tests command** — execute `pytest` on generated test files directly from VS Code
- **Auto-run setting** — optionally run tests immediately after generation (`testgen.autoRunTests`)
- **Cancellable project scan** — abort long-running project-wide generation
- Engine unit tests (`tests/`) for analyzer, validator, generator, and scanner

### Fixed
- Removed hardcoded API key from `run.py` (security fix)
- Fixed `NameError` crash when running with `--no-validate` flag
- Fixed `testgen.runTests` command registration (was listed but never implemented)
- Scanner now correctly receives `baseUrl` and `model` settings from VS Code

### Changed
- `run.py` now reads API keys exclusively from environment variables
- Improved `.gitignore` and `.vscodeignore` coverage
- Added LICENSE file (MIT)

## [0.3.0] - 2026-10-04

### Added
- Project-wide scanning (`testgen.generateForProject`)
- Project configuration via `.testgenrc.json`
- Config initialization command (`testgen.initConfig`)
- Rate limiting between API calls during batch generation

## [0.2.0] - 2026-10-02

### Added
- Cross-file dependency analysis (AST-based import resolution)
- Framework detection (FastAPI, Flask, Django, SQLAlchemy, etc.)
- Workspace fixture discovery (reuse existing `conftest.py` fixtures)
- AST validation with self-healing retry loop
- Dual API key fallback with automatic retry on 429/503

## [0.1.0] - 2026-09-30

### Added
- Initial release
- Function-level test generation via CodeLens
- File-level test generation via context menu
- Secure API key storage (VS Code SecretStorage)
- Support for Gemini, OpenAI, and any OpenAI-compatible API
- CLI usage via `engine/main.py`
