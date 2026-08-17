# Database Setup and Migrations

This document explains the database architecture, user roles, and migration workflow using Alembic.

## Database Architecture

### Two-Role Security Model

The application uses a **two-role security model** to separate schema management from runtime operations:

#### 1. Migrator User (`migrator_user`)
- **Purpose**: Owns the database schema and runs Alembic migrations
- **Permissions**: Full DDL rights (CREATE, ALTER, DROP tables/indexes/sequences)
- **Usage**: Only used during migrations, never by the running application
- **Configuration**: `MIGRATOR__USER`, `MIGRATOR__PASSWORD`, `MIGRATOR__DB` in `.env`

#### 2. Application User (`app_user`)
- **Purpose**: Runtime database operations for the application
- **Permissions**: DML only (SELECT, INSERT, UPDATE, DELETE) - **NO DDL rights**
- **Usage**: Used by the FastAPI application at runtime
- **Configuration**: `DATABASE__USER`, `DATABASE__PASSWORD`, `DATABASE__DB` in `.env`
- **Security**: Cannot accidentally drop tables or modify schema

### Why Two Roles?

This separation provides:
- **Security**: Runtime app cannot modify schema even if compromised
- **Safety**: Prevents accidental schema changes during normal operations
- **Audit**: Clear separation between schema changes (migrations) and data operations
- **Best Practice**: Standard production database security pattern

## Configuration Files

### `.env` File
Contains credentials and database connection details:

```bash
# PostgreSQL superuser (container bootstrap only)
POSTGRES_DB=backend
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# Migrator role: runs Alembic, owns the schema
MIGRATOR__USER=migrator_user
MIGRATOR__PASSWORD=migrator_password
MIGRATOR__DB=backend

# Application role: runtime DML only
DATABASE__USER=app_user
DATABASE__PASSWORD=app_password
DATABASE__DB=backend
```

### `config.yaml` (Local Development)
Used when running locally (outside Docker):

```yaml
database:
  user: app_user
  host: localhost
  port: 5432
  db: backend

migrator:
  user: migrator_user
  host: localhost
  port: 5432
  db: backend
```

- `host: localhost` connects to Docker-exposed PostgreSQL on port 5432
- Passwords come from `.env` via environment variables

### `config.docker.yaml` (Docker Environment)
Used inside Docker containers:

```yaml
database:
  user: app_user
  host: db
  port: 5432
  db: backend

migrator:
  user: migrator_user
  host: db
  port: 5432
  db: backend
```

- `host: db` uses Docker service name for internal networking
- Mounted as `/app/config.yaml` in containers via docker-compose

## Database Initialization

The database is initialized automatically when Docker starts:

1. **PostgreSQL container** runs `deploy/init_db.sh` and `deploy/init_db.sql`
2. **Creates two roles**: `migrator_user` and `app_user`
3. **Sets permissions**:
   - Migrator owns the `public` schema
   - App user gets automatic DML rights on all tables created by migrator
4. **Migrate service** runs `alembic upgrade head` to create tables
5. **App service** starts and connects using `app_user`

## Alembic Migrations

### Creating a New Migration

**Rule**: All table management MUST be done through Alembic. Never create tables manually or via `Base.metadata.create_all()`.

#### Step 1: Define Your Model

Create or modify a SQLAlchemy model in the relevant feature module, for example `src/backend/products/models.py`:

```python
# src/backend/products/models.py
from sqlalchemy import String, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..mixins import IntegerPrimaryKeyMixin, TimestampMixin


class ProductModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
```

#### Step 2: Register the Model

The model registry at `src/backend/db/registry.py` imports every feature model so Alembic can discover it. The registry is maintained automatically by the model registry pre-commit hook; do not edit it by hand.

After adding the model, run the repository's pre-commit checks to update the registry before generating the migration.

#### Step 3: Generate the Migration

**Option A: Run locally** (requires local database access):
```bash
uv run alembic revision --autogenerate -m "add products table"
```

**Option B: Run in Docker**
```bash
docker-compose run --rm migrate uv run alembic revision --autogenerate -m "add products table"
```

This creates a new file in `alembic/versions/` like `abc123_add_products_table.py`.

#### Step 4: Review the Migration

Review the generated migration file:

```python
def upgrade() -> None:
    op.create_table('products',
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )

def downgrade() -> None:
    op.drop_table('products')
```

Make manual adjustments if needed (e.g., add indexes, constraints).

#### Step 5: Apply the Migration

**In Docker** (automatic on restart):
```bash
docker-compose restart backend-migrate backend-app
```

**Locally**:
```bash
uv run alembic upgrade head
```

The migration runs using `migrator_user` credentials, creating tables owned by that role.

### Common Migration Commands

```bash
# Create a new migration (autogenerate from models)
uv run alembic revision --autogenerate -m "description"

# Create an empty migration (manual changes)
uv run alembic revision -m "description"

# Apply all pending migrations
uv run alembic upgrade head

# Apply migrations up to a specific revision
uv run alembic upgrade abc123

# Rollback one migration
uv run alembic downgrade -1

# Rollback to a specific revision
uv run alembic downgrade abc123

# Show current revision
uv run alembic current

# Show migration history
uv run alembic history

# Show pending migrations
uv run alembic heads
```

## Docker Compose Services

### `db` Service
- PostgreSQL 18 database
- Runs initialization scripts on first start
- Exposes port 5432 to host for local development

### `migrate` Service
- Runs once on startup: `alembic upgrade head`
- Uses `migrator_user` credentials
- Exits after migrations complete
- `restart: "no"` ensures it doesn't restart automatically

### `app` Service
- Runs the FastAPI application
- Uses `app_user` credentials (DML only)
- Depends on `migrate` service completing successfully
- Hot-reload enabled for development

## Best Practices

### DO:
- ✅ Always use Alembic for schema changes
- ✅ Review autogenerated migrations before applying
- ✅ Test migrations in development before production
- ✅ Keep migration files in version control
- ✅ Use descriptive migration messages
- ✅ Add indexes and constraints in migrations
- ✅ Use `migrator_user` for migrations only

### DON'T:
- ❌ Never use `Base.metadata.create_all()` in production
- ❌ Never grant DDL rights to `app_user`
- ❌ Never modify applied migrations (create a new one instead)
- ❌ Never skip migrations or apply them out of order
- ❌ Never commit `.env` file to version control
- ❌ Never hardcode credentials in code

## Troubleshooting

### "Permission denied for schema public"
- **Cause**: App is trying to create tables (DDL operation)
- **Solution**: Remove `Base.metadata.create_all()` calls, use Alembic migrations

### "could not translate host name 'db'"
- **Cause**: Running locally with `config.yaml` pointing to `host: db`
- **Solution**: Use `host: localhost` in `config.yaml` for local development

### Migration not detected
- **Cause**: Model is not imported by `src/backend/db/registry.py`
- **Solution**: Run the model registry pre-commit hook and verify the feature model appears in the registry

### Migration fails with "relation already exists"
- **Cause**: Table was created manually or migration applied twice
- **Solution**: Either drop the table or mark migration as applied: `alembic stamp head`

## Migration Workflow Summary

1. **Define model** in the relevant feature's `models.py`
2. **Update the registry** with the model registry pre-commit hook
3. **Generate migration**: `uv run alembic revision --autogenerate -m "description"`
4. **Review migration** file in `alembic/versions/`
5. **Apply migration**: `uv run alembic upgrade head` or restart Docker
6. **Commit** migration file to version control
7. **Deploy** to production (migrations run automatically via `migrate` service)

## References

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/orm/)
- [PostgreSQL Privileges](https://www.postgresql.org/docs/current/ddl-priv.html)
