# Testing Guide

This document describes the testing philosophy, patterns, and conventions used in
this repo. Read it before writing tests for a new feature.

## Testing Philosophy

### Unit tests

Test **pure functions** — code where input → output is deterministic and no
external state is involved. If a test needs to mock 20 things just to verify
that a mock returns what you expected, it's worthless. Unit tests should:

- Be **super fast** (milliseconds, no I/O, no DB, no network).
- Test something **real** — a transformation, a calculation, a validation, a
  parsing edge case.
- Use lightweight stand-ins (`SimpleNamespace`, plain dicts) instead of heavy
  mocks when the function under test accepts duck-typed inputs.
- Not need `async` unless the function itself is async and testable without a
  DB or external service.

**Example:** `tests/unit/test_export_service.py` tests `_build_row()` — a pure
function that maps a company + optional Excel row + prediction into an ordered
list of export columns. No DB, no fixtures, no mocks. Just `SimpleNamespace`
objects and assertions on the output.

### Integration tests

Test that **multiple components work together** — repository + DB, service +
repository, route + service + DB. They run against a real Postgres instance
(`backend_test` database) and can be slow (up to ~1s per test). External
dependencies like LLMs are mocked to avoid spending money on every CI run.

Integration tests should:

- Use a **real database** (Postgres via Docker in CI, local instance in dev).
- Test **services** primarily — routes generally just call services, so the
  service layer is where the logic lives.
- Test **routes** too, but focus on HTTP semantics (status codes, response
  shape, headers) rather than re-testing service logic through the route.
- Mock **external calls** (LLM APIs, network requests) with `monkeypatch`.
- Cover both the **happy path** and the **failure path** — create test cases
  that raise hard-to-reproduce exceptions (zombie processes, network errors,
  external service failures) so you know the code is tolerant to failure.

**Example:** `tests/integration/test_model_run_execution.py` tests the full
model execution flow — creates a project, starts a run, verifies predictions
are written, stops the run, checks partial results. LLMs are mocked with
`MockClassificationModel` that returns canned results.

### E2E tests (planned, not yet implemented)

Test **complex workflows chained end-to-end** through the API. They call the
HTTP endpoints directly, may access the DB to verify state, and check that
multi-step flows work correctly:

- Create project → upload file → ingest → run model → check predictions.
- Create project → start run → stop run → verify partial results → restart.

E2E tests live in `tests/e2e/` and are marked `@pytest.mark.e2e`.

### Fuzzy tests (planned, not yet implemented)

Test complex functionality against **randomly generated samples** to find edge
cases that hand-written tests miss. "Randomly" means the sample is created
randomly, but the process **stresses important parts of the functionality** —
it's not just "hope and pray." Use property-based testing (e.g. `hypothesis`)
to:

- Generate random inputs within valid constraints.
- Assert **invariants** that must always hold (e.g. "after sorting, the list
  is monotonically increasing").
- Run enough iterations to catch edge cases (empty lists, single element,
  duplicates, boundary values).

Fuzzy tests live alongside unit or integration tests and are marked
`@pytest.mark.fuzzy`.

---

## Test Organization

```
tests/
├── conftest.py              # Shared fixtures (see below)
├── unit/                    # Pure-function tests, no DB
│   └── test_*.py
├── integration/             # DB-backed tests, mocked externals
│   └── test_*.py
├── e2e/                     # (planned) full workflow tests via HTTP
└── factories/               # (planned) random data generators
```

Every test file starts with a marker:

```python
pytestmark = pytest.mark.integration  # or pytest.mark.unit
```

CI runs them as separate jobs: `pytest -m unit` then `pytest -m integration`.

---

## Fixtures (`tests/conftest.py`)

### `db_manager` (function-scoped)

Creates a real `DatabaseManager` pointing at the `backend_test` database. Each
test gets its own engine on its own event loop (asyncpg connections are
loop-bound, so a session-scoped engine would raise "attached to a different
loop").

```python
@pytest_asyncio.fixture
async def db_manager(app_config) -> DatabaseManager:
    manager = DatabaseManager(app_config.database)
    yield manager
    await manager.close()
```

### `db_session` (function-scoped)

A standalone `AsyncSession` for direct repository/service testing. **Always
rolls back** — no data persists between tests. This is the default for
repository tests.

```python
async def test_create_and_get(db_session):
    repo = ProjectRepository(db_session)
    project = await repo.create(ProjectCreate(name="Test"))
    assert project.name == "Test"
    # rollback happens automatically — no cleanup needed
```

### `app` (function-scoped)

A FastAPI app with dependency overrides for testing:

- `get_db_session` → **rollback-only** session (requests don't persist).
- `get_db_manager` → the test's `db_manager` (so background tasks use the
  correct database — see the `test_replace_run` bug for why this matters).
- `get_current_user` / `get_current_admin_user` → a fixed `_TEST_USER` (no
  real auth, no DB row needed).

### `async_client`

An `httpx.AsyncClient` against the ASGI transport. Uses the rollback `app`, so
read-only view tests are fully isolated.

### `client`

A synchronous `TestClient` for simple endpoint tests.

---

## Two Session Strategies

### Rollback sessions (default)

Used by `db_session` and `async_client`. Fast, isolated, no cleanup. The
session rolls back on close, so nothing persists. Use this when:

- Testing repository CRUD operations.
- Testing read-only views (GET requests).
- Testing service functions where you don't need data to survive across
  requests.

### Committing sessions (explicit, per-fixture)

Used when the test needs data to **survive across requests** or when
**background tasks** need to see committed rows. The pattern:

1. Open `db_manager.async_session()`, add rows, `await db.commit()`, capture IDs.
2. Yield the IDs or an env object.
3. Teardown: open a new session, `DELETE` each row by ID, `await db.commit()`.

```python
@pytest_asyncio.fixture
async def seeded_user(db_manager):
    async with db_manager.async_session() as db:
        user = UserModel(name="test-admin", email="test-admin@test.local")
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    yield user_id

    async with db_manager.async_session() as db:
        await db.execute(delete(UserModel).where(UserModel.id == user_id))
        await db.commit()
```

**When to use committing sessions:**

- HTTP view tests where a POST must persist so a subsequent GET can see it.
- Background task tests (the task opens its own session and can only see
  committed rows).
- Any test where the app's request-scoped session (which rolls back) can't see
  rows from the test's session.

**The `committing_client` fixture** — a variant of `async_client` where the
`get_db_session` override **commits** instead of rolling back. Used for
write-then-read view tests (e.g. submit a judgment, then check it appears in
the list).

---

## User Creation Patterns

### Stub user (conftest `_TEST_USER`)

A Pydantic `User` with `id=1` that never touches the DB. The dependency
override returns it directly. Use when the route only reads `user.id` /
`user.role` — no FK constraints to satisfy.

```python
_TEST_USER = User(id=1, name="test-user", email="test-user@test.local", ...)
```

### Committed user (`committing_user` fixture)

A real `UserModel` row inserted and committed, then returned as a Pydantic
`User`. Use when FK constraints require the user to exist (e.g.
`feedback_set_by`, `created_by_id`). Cleaned up in teardown.

---

## Mocking External Dependencies

### LLMs and model registry

Use `monkeypatch.setitem` to swap a registered model for a test stub:

```python
monkeypatch.setitem(MODEL_REGISTRY, "llm-classification", MockClassificationModel)
```

The mock is a plain class with an `async def run(samples, config, classes=None)`
method that returns canned results. No API calls, no money spent. `monkeypatch`
auto-reverts after the test.

```python
class MockClassificationModel:
    config_type = None

    async def run(self, samples, config, classes=None):
        return [
            ClassificationResult(predicted_class="KEEP", score=0.9, duration_ms=1.0)
            for _ in samples
        ]
```

### Simulating hard-to-reproduce failures

Create mock classes that trigger edge cases mid-execution:

```python
class StopAfterFirstBatchModel:
    """Sets stop_requested mid-batch via its own committing session,
    simulating a user clicking 'stop' while a batch is in flight."""
    async def run(self, samples, config, classes=None):
        if type(self).calls == 1:
            async with type(self).db_manager.async_session() as db:
                await ProjectModelRunRepository(db).request_stop(type(self).run_id)
        return [ClassificationResult(...) for _ in samples]
```

This tests the stop-gracefully path without relying on timing or sleeps.

---

## Env Objects

When a test needs a complex graph of committed rows (project + user + model
instance + version + companies + predictions), bundle setup + teardown into an
env class:

```python
class ModelRunEnv:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.project_id = None
        self.user_id = None
        self.version_id = None
        self.company_ids = []
        self.run_ids = []
        self.task_ids = []

    async def setup(self, model_type="llm-classification"):
        # Create all rows on a committing session, store IDs
        ...

    async def cleanup(self):
        # Delete everything in reverse FK order
        ...
```

The fixture yields the env, the test reads from it, teardown cleans up:

```python
@pytest_asyncio.fixture
async def env(db_manager):
    env = ModelRunEnv(db_manager)
    await env.setup()
    yield env
    await env.cleanup()
```

**Delete in reverse FK order** — children before parents — to avoid constraint
violations.

---

## Naming and Uniqueness

Use `_unique("label")` to append a random suffix to names and emails. This
prevents collisions when tests run in parallel or when committed rows from a
previous run weren't cleaned up:

```python
def _unique(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:12]}"
```

---

## What to Test

### Happy path

- Create → read → update → delete cycle works.
- Expected side effects (predictions written, task status updated, etc.).
- Response shape and status codes match the documented `responses` dict.

### Failure path

- Missing record returns 404 / None.
- Invalid input returns 400 / validation error.
- Concurrent operations are rejected or handled gracefully.
- External dependency failures (network errors, zombie processes) don't wedge
  the system — the code recovers or fails cleanly.

### Edge cases

- Empty collections (no companies to score, no predictions yet).
- Boundary values (pagination offset at the end, empty string vs None).
- UUIDv7 vs stdlib UUID comparison (they compare equal but hash differently —
  key dicts by `str(id)` if you mix the two).
