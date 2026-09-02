# Menelao
Menelao is a RAG solution that solves two distinct problems:
1. Creating and managing Knowledge Bases (KBs).
2. Serving the content of knowledge bases through MCP and agentic interfaces.

While this project is initially being used for managing post-acquisition documents, it also has the ambition to become the de facto tool for managing knowledge bases of any type.
RAG applications are pretty straightforward and general. We will provide a set of shared components that can work in any domain.
At the same time, specific components will be provided for specific file types: for example, if churn Excel files have a predictable structure, rather than simply parsing an Excel file, we can handle it in a specific way, compute metrics, and provide this information in the converted text.

## Installation
To install all dependencies, run:
```bash
bash setup.sh
```
This repository ships a harness that can be installed as an MCP tool for your favourite agentic tool.
If you are interested, run:
```
bash setup.sh --harness
```
While the installation process is Unix-based, the harness can also work on Windows.
The harness provides agents with a systematic way to create containers, run tests, and take screenshots of the application.

If you are a Windows developer, let's work together to create an equivalent `setup.bat` script. The application can still be run and developed with the help of Docker, but I think it is valuable to have access to a pure development environment.


## Structure of the solution
This repository hosts the code for different components:
1. A FastAPI backend under `/api/`.
2. A [JinjaX](https://jinjax.scaletti.dev/guides/) frontend at the root of the application.
3. An MCP server.

The FastAPI backend follows what I would call a traditional module structure: every module has a specific responsibility, with the following files:
- `exceptions.py`: contains exceptions.
- `schemas.py`: contains schemas for the routes.
- `models.py`: contains database models.
- `repository.py`: contains more or less complex CRUD operations.
- `service.py`: links multiple repositories and functionalities, performs checks, and contains functionality that can be used in multiple parts of the application: views, routes, and MCP.
- `routes.py`: FastAPI JSON routes.
- `views.py`: JinjaX routes that serve HTML.

The frontend is written with JinjaX.
It is an HTML templating language that allows developers to write HTML, CSS, and JavaScript code with the same reusable-component ideas as React, without the full React complexity.
I am a big fan of server-side rendering for a variety of reasons:
1. I understand React at a very high level, but I find JavaScript code very hard to parse.
2. I can read HTML code quite fluently.
3. I find modern JavaScript setups very complex, and I am not knowledgeable enough to use them properly.
4. JinjaX adds the *component* idea on top of HTML development. It is very intuitive, and the state is managed by the backend, in a language and framework with which I am very knowledgeable.
5. This setup has zero frontend build time, which is infinitely better than running `docker` + `npm install`.
6. I do not have to serve and manage a separate frontend container.
7. It is more fun to create components and learn new things.

Here is the structure of the frontend package:
- **`common/`** — Reusable primitives: Button, Card, Field, Dialog, Alert, Divider, Pill, Table, Icon, Avatar.
- **`layout/`** — Page shells: BlankPage (bare HTML), Page (with sidebar), Sidebar (M3 navigation drawer).
- **`pages/`** — Full pages composed from common and layout: admin dashboard, home, login, showcase.

I am aware that this setup is controversial and that it has some drawbacks, but I believe I am presenting good arguments that show JinjaX is the right tool.

## Agentic Coding Philosophy
At the time of writing, I still think it is important that both humans and AI understand code.
The JinjaX setup, the opinionated FastAPI setup, and the different harnesses that can also be used via the CLI by humans all work toward this goal.
The hope is to have an application that is easy to maintain in six months, rather than speed-running the first 24 hours.

Code quality is enforced automatically whenever possible with `pre-commit` hooks. Formatting and Linting for sure, but even automatic import generation, checks on JinjaX templates, and much more.

In my experience, very long, complex and convoluted prompts generate very verbose code. I prefer to give some decent examples in the repository and then

### Conceptual Integrity

Bugs happen because code is not tested. They also happen because the underlying domain changes, and what made sense six months ago no longer does. Change is inevitable, but we should write software that is easy to change: it should be easy to understand where things are, and changes made in one place should not have repercussions in another, distant place. This holds for humans and AI alike.

## Development
### Local development

The application configuration is split into two pieces:
1. A versioned YAML file for values that are not secrets, such as hosts, ports, and enabled features.
2. A local `.env` file for passwords, API keys, and other secrets.

For normal local development, these files are `config.yaml` and `.env`. Docker uses `config.docker.yaml` instead, because containers reach PostgreSQL at `db` rather than `localhost`. Environment variables take precedence over YAML, so a value can be overridden without changing the versioned configuration.

Start by creating `.env` from `.env.example`. Add `AUTH__JWT_SECRET`, which is required by the backend, and add `ANTHROPIC_API_KEY` if you want Open WebUI to call Anthropic.

### Docker Compose

The simplest way to run the whole application is:

```bash
docker compose up --build
```

This starts PostgreSQL, runs Alembic migrations, then starts the backend at `http://localhost:8001` and Open WebUI at `http://localhost:3000`.

It is also possible to start only PostgreSQL and run the backend from the host:

```bash
docker compose up -d db
DATABASE__PORT=5434 MIGRATOR__PORT=5434 uv run alembic upgrade head
DATABASE__PORT=5434 uv run uvicorn src.backend.server:create_app --factory --reload
```

There is also a `uv` Compose service for one-off commands in the container environment. For commands that need the application configuration, such as migrations, use the configured `migrate` service instead:

```bash
docker compose run --rm migrate
docker compose run --rm migrate alembic current
docker compose run --rm migrate alembic revision --autogenerate -m "add a table"
```

The first command runs the configured `alembic upgrade head` migration command. The `uv` service is useful for generic commands that do not need the application configuration.

### Menelao harness

The harness creates isolated test environments. It is useful for agents and automated tests, rather than as the usual way to develop the application:

```bash
uv run menelao harness env up --mode docker
uv run menelao harness env teardown
```

The `docker` mode starts a database, backend, and Open WebUI on available local ports. The `local` mode starts only an isolated PostgreSQL database. The harness uses `.env.test` and temporarily adapts `config.test.yaml`, rather than the normal local `.env` and `config.yaml`.

## Testing Philosophy

This template follows a testing philosophy drawn from experience.
In general, unit testing is not very useful for API development, since most API calls are a chain of simple operations.
I personally despise mocks, but I understand their use cases.

### Unit Tests
**Runtime:** Milliseconds.
**Purpose:** Test isolated, pure functions/classes without external dependencies.

- Test simple, self-contained components (e.g., string validators, calculators).
- Avoid mocking when possible.
- If a component requires a database session, use integration tests instead.

**Objective:** Ensure individual functions work correctly and prevent regressions.

### Integration Tests
**Runtime:** Seconds.
**Purpose:** Test business logic with real database connections.

- Test `service.py` and `repository.py` with actual database connections.
- Test `routes.py` using FastAPI's test client (no server required).
- Mock only external dependencies (APIs and third-party services).
- Verify both application logic and database state.
- Focus on error handling when external dependencies fail.

**Objective:** Ensure features work correctly end-to-end and maintain functional consistency.

### End-to-End Tests
**Runtime:** Seconds to minutes.
**Purpose:** Test complete user workflows from an external perspective.

- Treat the application as a black box (no access to internal state).
- Database access is allowed for verification only.
- No mocking.
- Cover complex, multi-step workflows requested by business stakeholders.
- Run after deployment to verify application integrity.

**Objective:** Ensure the application meets business requirements in a production-like environment.

### Fuzzy Tests
**Runtime:** Minutes.
**Purpose:** Test application robustness with random inputs.

- Generate random inputs to explore multiple code paths.
- Useful when test cases are easy to generate programmatically.
- Focus on statistical properties rather than specific behaviours.
- Can be applied at any test level (unit, integration, or E2E), while respecting their requirements.

**Objective:** Discover edge cases and ensure system stability under unexpected inputs.

### Performance Tests
**Runtime:** Heavily dependent.
**Purpose:** Measure system performance under load and identify bottlenecks.

- Test response times, throughput, and resource utilization under various load conditions.
- Identify performance degradation points (e.g., database query optimisation and caching needs).
- Benchmark critical endpoints to establish performance baselines.
- Simulate realistic traffic patterns and concurrent user scenarios.
- Monitor memory usage, CPU utilization, and database connection pools.

**Objective:** Ensure the application meets performance requirements and scales appropriately under production load.
