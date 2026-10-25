# Python / FastAPI

## Environments and packages
```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements/dev.txt
pip config set global.index-url https://<internal-mirror>/simple       # corporate mirror
pip download -r requirements/ingestion.txt -d wheels/                  # on a connected box (same OS/arch/Python!)
pip install --no-index --find-links wheels/ -r requirements/ingestion.txt   # offline install
pip freeze | grep -i -E "fastapi|pydantic|ag-ui|portkey|elasticsearch"
pip check                                                               # dependency conflicts
python -c "import sys; print(sys.version)"
```

## Tests
```bash
pytest -q                                   # unit (ingestion + api)
pytest tests/api/test_agui_contract.py -q -k approval -x -vv
pytest -m integration                       # needs TEST_DATABASE_URL
pytest --lf                                 # rerun last failures
python -m ruff check services apps/opsi-api tests
```

## Run the lab app
```bash
cd apps/opsi-api
OPSI_ENV=lab OPSI_AUTH_MODE=dev uvicorn app.main_example:lab_app --factory --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/api/v2/healthz
curl -s http://127.0.0.1:8000/openapi.json | jq '.paths | keys'
```

## Debugging
```bash
python -X dev -m opsi_ingest status          # extra runtime warnings
python -m pdb -m opsi_ingest collect --source elastic --dry-run
PYTHONASYNCIODEBUG=1 uvicorn ...             # slow callbacks / un-awaited coroutines
```
In code: `breakpoint()`; inspect pydantic errors with `exc.errors()`.

## FastAPI patterns used in the kit
- Dependencies: `Depends(require("chat:use"))` -> Principal; `Depends(services)` -> container on `app.state.opsi`.
- Models with `ConfigDict(extra="forbid")` -> unknown fields are 422.
- Streaming: `StreamingResponse(generator, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})`.
- Blocking SDK calls inside async handlers -> `anyio.to_thread.run_sync(...)` / `asyncio.to_thread(...)`.
