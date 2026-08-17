# Project Guidelines

This file is reserved for coding agents.
Be concise, both when talking and writing code.
Every line of code is a potential liablity, so a solution should not add useless complexity.
A change done in a file in general should not have a ripple effect on a very distant unrelated file.
If there is a bug, the bug should be as much as possible local to the place where it happened.


## Tools
If available in your environemnt, use
- haystack MCP when creating haystack pipelines
- semble: semble mcp is superfast and superaccurate searhc tool. use it instead of ytour usual tools and grep searches. use these tools only if semble did not give you an answer.

## Project Structure

Keep the repository organized by responsibility rather than listing every module here:

- `src/backend/` contains the FastAPI application. Keep each domain in a self-contained feature module.
- `src/frontend/` contains JinjaX components and static assets.
- `alembic/` contains database migrations; `deploy/` contains deployment configuration.
- `docs/` contains workflows and project-specific technical guidance.
- Root configuration belongs in files such as `config.yaml`, `pyproject.toml`, and `alembic.ini`.

A typical backend feature looks like this:

```
src/backend/<feature>/
├── routes.py       # JSON API endpoints
├── views.py        # HTML/htmx endpoints, when needed
├── schemas.py      # Request and response models
├── service.py      # Business logic and database queries
├── models.py       # SQLAlchemy models, when needed
└── exceptions.py   # Feature-specific exceptions
```

Use existing neighboring features as the source of truth. Shared infrastructure belongs in the appropriate top-level backend module, not in a feature merely because it is convenient there.

### Feature Organization

Features under `src/backend/` should be self-contained. Routes and views handle transport, schemas handle validation, and services own business logic and SQLAlchemy queries. JSON and HTML/htmx routes should share the same service layer.

### Frontend

The frontend uses [JinjaX](https://jinjax.scaletti.dev/) for server-rendered components and [htmx](https://htmx.org/) for dynamic interactions — no client-side framework. The [`json-enc`](https://github.com/bigskysoftware/htmx-extensions/blob/main/src/json-enc/README.md) htmx extension encodes form submissions as JSON payloads. Components live in `src/frontend/components/` and follow Material Design 3-inspired patterns with CSS custom-property design tokens.

- **`common/`** — Reusable primitives: Button, Card, Field, Dialog, Alert, Divider, Pill, Table, Icon, Avatar
- **`layout/`** — Page shells: BlankPage (bare HTML), Page (with sidebar), Sidebar (M3 navigation drawer)
- **`pages/`** — Full pages composed from common + layout: admin dashboard, home, login, showcase

See `docs/jinjax.md` for component conventions, htmx patterns, and asset loading rules.
Each new module generally gets its own page.

## Testing

Unit testing is rarely useful for API development since most API calls are a chaining of simple operations. Prefer integration tests and avoid mocks except for external services.

- **Unit (ms):** Test pure logic only; use integration tests for database-dependent code.
- **Integration (s):** Use a real database and FastAPI's test client; verify behavior and database state.
- **E2E (s–min):** Test complete workflows as a black box without mocks.
- **Fuzzy/performance (min+):** Add these when robustness or load behavior matters.

## New Feature Workflow

Work in small increments: implement one layer, test it, then move on. Do not write the whole feature in one pass.

### Modifying an existing feature

1. Understand what needs to change and where it lives.
2. Make the smallest change that moves toward the goal.
3. Add or update tests for that change.
4. Run the tests. Repeat until the feature is done.

### Creating a new feature

1. Create the feature module under `src/backend/<feature>/` (see the structure above).
2. Add the SQLAlchemy model, then the schemas, exceptions, service, and routes — one layer at a time, testing each before continuing.
3. Register the router in `server.py`.
4. Add the frontend: a new page, and a new component only if no existing one fits. Reuse `common/` and `layout/` primitives as much as possible.
5. If the feature needs functionality from another module, call that module's service (preferred) or repository — do not duplicate its logic.

### Tests

Cover happy path, error path, and any non-trivial case (concurrent access, partial input, external dependency failure). See `docs/new_feature_workflow.md` for the detailed checklist.

## Database and Migrations

This project uses **PostgreSQL** with **Alembic** for schema migrations and a **two-role security model**:

- **`migrator_user`**: Owns the schema, runs migrations (DDL rights)
- **`app_user`**: Runtime application user (DML only - no table creation/modification)

### Key Principles

- ✅ **All table management MUST be done through Alembic migrations**
- ❌ Never use `Base.metadata.create_all()` in production
- ❌ Never grant DDL rights to the runtime application user

### Quick Migration Workflow

1. Define your SQLAlchemy model in the relevant feature module, e.g. `src/backend/users/models.py`
2. Ensure the model registry is updated by the model registry pre-commit hook
3. Generate migration: `uv run alembic revision --autogenerate -m "description"`
4. Review the generated file in `alembic/versions/`
5. Apply migration: `uv run alembic upgrade head` (or restart Docker)

See **`docs/database_migrations.md`** for complete documentation on:
- Database architecture and security model
- Configuration files (`.env`, `config.yaml`, `config.docker.yaml`)
- Detailed migration workflows
- Best practices and troubleshooting
