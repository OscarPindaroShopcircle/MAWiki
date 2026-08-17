# New Feature Workflow

This guide walks through creating a new feature from scratch. Use this as a checklist when adding new functionality.

## Prerequisites

- Read [sqlalchemy.md](./sqlalchemy.md) for model conventions
- Read [schemas.md](./schemas.md) for Pydantic schema conventions
- Read [fastapi.md](./fastapi.md) for route and service conventions

## Step-by-Step Workflow

### 1. Create Feature Folder

Create a new folder under `src/backend/` with the feature name:

```
src/backend/feature_name/
├── __init__.py      # Empty file
├── routes.py        # API endpoints
├── schemas.py       # Pydantic models
├── service.py       # Business logic
└── exceptions.py    # Feature-specific exceptions
```

### 2. Create SQLAlchemy Model

**Location:** `src/backend/feature_name/models.py`

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..mixins import IntegerPrimaryKeyMixin, TimestampMixin


class FeatureModel(Base, IntegerPrimaryKeyMixin, TimestampMixin):
    # Add your fields here
    name: Mapped[str] = mapped_column(String(255), nullable=False)
```

**Important:** The model registry at `src/backend/db/registry.py` must import every feature model. It is maintained automatically by the model registry pre-commit hook; do not edit it by hand. Run the repository's pre-commit checks after adding the model.

### 3. Create Pydantic Schemas

**Location:** `src/backend/feature_name/schemas.py`

Create the following schemas:
- `FeatureCreate` - Input for creation (only writable fields)
- `Feature` - Internal representation (all fields)
- `FeatureResponse` - API response
- `FeatureUpdate` - Input for PATCH updates

Use `AppBaseModelStripped` for user input (auto-strips whitespace).
Use `Annotated` with `Field` for validation and documentation.

See [schemas.md](./schemas.md) for complete examples.

### 4. Create Exceptions

**Location:** `src/backend/feature_name/exceptions.py`

```python
from fastapi import HTTPException, status


class FeatureNotFound(HTTPException):
    def __init__(self, feature_id: int):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Feature with id {feature_id} not found",
        )
```

### 5. Create Service Layer

**Location:** `src/backend/feature_name/service.py`

Implement business logic functions:
- `create_feature(db, data)` → Create new record
- `get_feature(db, id)` → Get single record
- `get_all_features(db)` → Get all records
- `update_feature(db, id, data)` → Update record
- `delete_feature(db, id)` → Delete record

Functions accept:
- `db: AsyncSession` - Database session (injected via dependency)
- Schema objects or IDs as needed

See [fastapi.md](./fastapi.md) for complete examples.

### 6. Create Routes

**Location:** `src/backend/feature_name/routes.py`

For each endpoint, include:
- **Docstring** - What the endpoint does
- **response_model** - Pydantic schema for response
- **status_code** - Appropriate HTTP status
- **responses** - Document all possible status codes

Standard CRUD endpoints:

| Method | Path | Status Codes |
|--------|------|--------------|
| POST | `/` | 201 (created) |
| GET | `/{id}` | 200 (found), 404 (not found) |
| GET | `/` | 200 (list returned) |
| PATCH | `/{id}` | 200 (updated), 404 (not found) |
| DELETE | `/{id}` | 204 (deleted), 404 (not found) |

Use `ListResponse[FeatureResponse]` for list endpoints.

### 7. Register Router

**Location:** `src/backend/server.py`

```python
from .feature_name.routes import router as feature_router

# In create_app():
app.include_router(feature_router)
```

## Checklist

- [ ] Feature folder created with `__init__.py`, `routes.py`, `schemas.py`, `service.py`, `exceptions.py`
- [ ] SQLAlchemy model created with appropriate mixins
- [ ] Model registry updated by the model registry pre-commit hook
- [ ] Pydantic schemas created (Create, Response, Update)
- [ ] Schemas inherit from `AppBaseModelStripped`
- [ ] Fields use `Annotated` with `Field` for validation and examples
- [ ] Exceptions created for error cases
- [ ] Service functions implemented for CRUD operations
- [ ] Routes created with proper documentation:
  - [ ] Docstrings
  - [ ] response_model
  - [ ] status_code
  - [ ] responses dict
- [ ] Router registered in `server.py`
- [ ] List endpoints use `ListResponse[T]` wrapper
