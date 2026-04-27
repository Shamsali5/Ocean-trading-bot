# Ocean Framework

## Legacy backup note

`ocean_telegram_runner.py` is kept as a legacy OpenAI-based runner backup and is not modified by the deterministic rebuild scaffold.

## Deterministic rebuild scaffold

The new deterministic engine package lives under `ocean_engine/` and currently includes typed models, enums, and module skeletons for future implementation.

## Running tests

Run tests from the repository root:

```bash
pytest -q
```

The repository-level `pytest.ini` adds `ocean_project/` to `PYTHONPATH`, so root test runs can import `ocean_engine` without extra setup.
