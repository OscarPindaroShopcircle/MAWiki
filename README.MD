# FastAPI Template

An opinionated FastAPI template with a structured approach to building backend applications. This template incorporates best practices from personal experience and the FastAPI community, heavily inspired by [this excellent repository](https://github.com/zhanymkanov/fastapi-best-practices).

## Philosophy
The idea is to give both human and coding agents a set of "good practices to follows". I put in this template the knowledge I gathered while working on my projects. This knowledge comes from direct experimentation and knowledge sharing with other people.

The core ideas behind this template are:

### Strong Typing

Use Pydantic models everywhere; never use dictionaries. Strong typing conventions make it clearer to developers which data they are manipulating and provide a lot of information about the state of the system.

### SQLAlchemy and Alembic

I worked on a repository with pure SQL strings; this will **not** happen again. SQLAlchemy provides a clear description of the database, eliminates the need for constant synchronization between code and documentation, and means that LLMs do not have to read the history of migrations to understand which columns are in the `projects` table.

### Static Checks

Some properties of code can be inferred and enforced before running it. Pre-commit hooks can be used to ensure consistent formatting and linting, avoid committing secrets, and require developers to use predefined variables and systems. If your project has a convention that can be enforced automatically, write a pre-commit hook.

### Testing

Unit, integration, end-to-end, and fuzz tests—you name it. Define clear rules for what each type of test can do and how long it can run. Make tests easy to run locally, either on the system or in Docker, and include them in a GitHub CI pipeline. Software should be written to be testable: do not put random global configuration variables in a module; otherwise, tests will have to mock half of the modules.

### Conceptual Integrity

Bugs happen because code is not tested. They also happen because the underlying domain changes, and what made sense six months ago no longer does. Change is inevitable, but we should write software that is easy to change: it should be easy to understand where things are, and changes made in one place should not have repercussions in another, far-away place.

## Prepackaged Functionalities

The current template can spin up an application with working user management. The application supports SSO with google or usernam and password authentication. User can join only via invitations.
On the frontend side, there are already some jinjax components for common necessities, like Buttons, Avatars, Sidebar and so on.

## Environment & Package Management

This repository uses `uv` for fast package and environment management. The structure is compatible with Poetry, but requires adjustments to `pyproject.toml`. I chose UV because it's blazing fast.

The application is packaged as the `backend` module. You can customize both the folder name and package parameters in `pyproject.toml`.

## Project Structure

```
fastapi-template/
├── alembic/                    # Database migrations
├── deploy/                     # Deployment configurations
│   ├── docker-compose.yaml
│   ├── init_db.sh
│   └── init_db.sql
├── docs/                       # Developer and LLM documentation
│   ├── testing.md             # Testing strategy
│   ├── user.md                # User and auth model
│   ├── clients.md             # External service client patterns
│   ├── database_migrations.md # Migration workflows and security model
│   └── new_feature_workflow.md # Step-by-step feature creation guide
├── src/
│   ├── backend/               # Main application package
│   │   ├── auth/              # Authentication: SSO, JWT, invitations, password
│   │   │   ├── routes/       # API routes (auth, invitations)
│   │   │   ├── service.py    # Auth business logic
│   │   │   ├── schemas.py    # Auth Pydantic models
│   │   │   ├── dependencies.py # get_current_user, get_current_admin_user
│   │   │   ├── exceptions.py  # Auth-specific HTTP exceptions
│   │   │   ├── tokens.py      # JWT creation/verification
│   │   │   ├── password.py    # Password hashing/verification
│   │   │   └── sso.py         # Google OAuth/OpenID
│   │   ├── users/             # User management feature
│   │   │   ├── routes.py     # API endpoints
│   │   │   ├── views.py      # HTML/htmx endpoints (admin pages)
│   │   │   ├── schemas.py    # Pydantic models
│   │   │   ├── service.py    # Business logic
│   │   │   ├── repository.py # Data access layer
│   │   │   └── exceptions.py # Feature-specific exceptions
│   │   ├── showcase/          # Component showcase (living style guide)
│   │   ├── agents/            # AI agents and agentic workflows
│   │   ├── clients/           # External service integrations
│   │   ├── tasks/             # Async task management
│   │   ├── files/             # File storage models
│   │   ├── db/                # Database layer
│   │   │   ├── db.py         # Base class and DatabaseManager
│   │   │   ├── mixins.py     # Reusable model mixins
│   │   │   ├── registry.py   # Central SQLAlchemy model registry
│   │   │   └── enums.py      # Shared database enums
│   │   ├── config.py          # Application configuration
│   │   ├── dependencies.py    # Shared dependencies (e.g., get_db_session)
│   │   ├── jinja.py           # JinjaX catalog + Jinja filters
│   │   ├── views.py           # Top-level HTML routes (home, login)
│   │   ├── schemas.py         # Base Pydantic models
│   │   └── server.py          # FastAPI app creation
│   └── frontend/              # JinjaX components and static assets
│       ├── components/        # Server-rendered UI components
│       │   ├── common/       # Reusable M3 primitives (Button, Card, Field, Dialog, …)
│       │   ├── layout/       # Page shells (BlankPage, Page, Sidebar)
│       │   └── pages/        # Full pages (admin, home, login, showcase)
│       └── static/           # CSS tokens, JS utilities, icons
├── config.yaml                 # Application configuration
├── pyproject.toml             # Project dependencies
└── alembic.ini                # Alembic configuration
```

### Feature Organization

Features are organized into self-contained modules under `src/backend/`. Each feature contains:
- `routes.py` - JSON API endpoints
- `views.py` - HTML/htmx endpoints (server-rendered pages and fragments)
- `schemas.py` - Pydantic models for request/response validation
- `service.py` - Business logic (all SQLAlchemy queries live here, never in routes/views)
- `repository.py` (optional) - Object-oriented data access layer
- `exceptions.py` - Feature-specific HTTP exceptions
- `models.py` - sqlalchemy models

API routes (`routes.py`) and HTML views (`views.py`) share the same service layer, ensuring functionality parity between JSON and htmx interfaces.

### Frontend

The frontend uses [JinjaX](https://jinjax.scaletti.dev/) for server-rendered components and [htmx](https://htmx.org/) for dynamic interactions — no client-side framework. The [`json-enc`](https://github.com/bigskysoftware/htmx-extensions/blob/main/src/json-enc/README.md) htmx extension encodes form submissions as JSON payloads. Components live in `src/frontend/components/` and follow Material Design 3-inspired patterns with CSS custom-property design tokens.

- **`common/`** — Reusable primitives: Button, Card, Field, Dialog, Alert, Divider, Pill, Table, Icon, Avatar
- **`layout/`** — Page shells: BlankPage (bare HTML), Page (with sidebar), Sidebar (M3 navigation drawer)
- **`pages/`** — Full pages composed from common + layout: admin dashboard, home, login, showcase

The showcase at `/components` is the living style guide — every `common.*` component must be added there with all variants visible. See `docs/jinjax.md` for component conventions, htmx patterns, and asset loading rules.

**Why Server Side Rendering**: In general I'm a one man band that has to gather requirements, develop the application, test it and host it. I know python very well, I am able to read html and css, i am very much not proficient in javascript. This setup has for me some important advantages:
- JinjaX uses a component approach, and therefore it looks more like class composition that random html tags.
- I can deploy a single container that hosts both API and frontend
- I don't have to learn React, Javascript, plus all the very fragmented ecosystem around these technologies
- htmx exposes almost a pure html experience, which is very easy to read to me
- i don't care about fancy animations
- In the last 20 years, servers got superpowerful. Using only a very small amount of power, we can create a very light frontend that instantly reacts to changes, without having to ship


## Documentation

The `docs/` folder contains comprehensive documentation for developers and LLMs:

- **`fastapi.md`** - FastAPI conventions, route patterns, and service layer guidelines
- **`schemas.md`** - Pydantic schema conventions and validation patterns
- **`sqlalchemy.md`** - SQLAlchemy model conventions and available mixins
- **`jinjax.md`** - JinjaX component system, htmx patterns, and frontend conventions
- **`testing.md`** - Testing strategy and test types
- **`user.md`** - User model, roles, and authentication flow
- **`clients.md`** - External service client patterns and best practices
- **`database_migrations.md`** - Database architecture, security model, and migration workflows
- **`new_feature_workflow.md`** - Complete checklist for adding new features

Documentation follows the same modular structure as the backend code.

## Configuration

The template includes a flexible configuration system that supports YAML files:

- Application settings can be defined in `config.yaml` with comments
- Secret fields are protected by pre-commit hooks and cannot be committed in YAML files
- Store secrets in `.env` files or your environment manager (e.g., Railway, AWS Secrets Manager)

**Example deployment workflow:**
1. Point your deployment to a specific `config.yaml` file
2. Load secrets through the platform's environment variable system

## Testing Philosophy

This template follows a testing drawn from experience.
In general, unit testing is not really useful for API development, since most of the API calls are a chaining of simple operations.
I personally despise mocks, but I understand their use cases.

### Unit Tests
**Runtime:** Milliseconds
**Purpose:** Test isolated, pure functions / classes without external dependencies

- Test simple, self-contained components (e.g., string validators, calculators)
- Avoid mocking when possible
- If a component requires a database session, use integration tests instead

**Objective:** Ensure individual functions work correctly and prevent regressions

### Integration Tests
**Runtime:** Seconds
**Purpose:** Test business logic with real database connections

- Test `service.py` and `repository.py` with actual database connections
- Test `routes.py` using FastAPI's test client (no server required)
- Mock only external dependencies (APIs, third-party services)
- Verify both application logic and database state
- Focus on error handling when external dependencies fail

**Objective:** Ensure features work correctly end-to-end and maintain functional consistency

### End-to-End Tests
**Runtime:** Seconds to minutes
**Purpose:** Test complete user workflows from an external perspective

- Treat the application as a black box (no access to internal state)
- Database access allowed for verification only
- No mocking
- Cover complex, multi-step workflows requested by business stakeholders
- Run after deployment to verify application integrity

**Objective:** Ensure the application meets business requirements in production-like conditions

### Fuzzy Tests
**Runtime:** Minutes
**Purpose:** Test application robustness with random inputs

- Generate random inputs to explore multiple code paths
- Useful when test cases are easy to generate programmatically
- Focus on statistical properties rather than specific behaviors
- Can be applied at any test level (unit, integration, or E2E), while respecting their requirements

**Objective:** Discover edge cases and ensure system stability under unexpected inputs

### Performance Tests
**Runtime:** heavily dependent
**Purpose:** Measure system performance under load and identify bottlenecks

- Test response times, throughput, and resource utilization under various load conditions
- Identify performance degradation points (e.g., database query optimization, caching needs)
- Benchmark critical endpoints to establish performance baselines
- Simulate realistic traffic patterns and concurrent user scenarios
- Monitor memory usage, CPU utilization, and database connection pools

**Objective:** Ensure the application meets performance requirements and scales appropriately under production load

## AI Agents

The `src/backend/agents/` folder contains AI agents and agentic workflows. Agents are autonomous components that can.

In the future, dedicated folders may be added for AI models and datasets as the project scales.

## External Service Integrations

The `src/backend/clients/` folder contains wrappers for external services and libraries. These clients provide a clean abstraction layer for:

- **Third-party APIs** - Payment processors, email services, SMS providers
- **AI/ML services** - OpenAI, Anthropic
- **Cloud services** - AWS S3, Google Cloud Storage, Azure services
- **Other external dependencies** - Search engines, analytics platforms

Clients encapsulate authentication, error handling, and retry logic, making external integrations easier to test and maintain.

See `docs/clients.md` for detailed conventions and examples.

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

## Quick Start

### Run a sample server
```bash
cp .env.example .env
docker-compose up --build
```

The application will:
1. Start PostgreSQL and create database roles
2. Run Alembic migrations to create tables
3. Start the FastAPI application on http://localhost:8000

Visit http://localhost:8000/docs for API documentation.

### Add new features

See `docs/new_feature_workflow.md` for a complete guide on adding new features to the application.
