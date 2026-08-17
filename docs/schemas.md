# Pydantic Schema Conventions

## Base Classes

All schemas must inherit from the app-specific base models located in `src/backend/schemas.py`:

| Base Class | Use Case |
|------------|----------|
| `AppBaseModel` | General schemas, preserves whitespace |
| `AppBaseModelStripped` | User input schemas, auto-strips whitespace from strings |
| `ListResponse[T]` | Wrap list responses for extensibility |

## Features Included in Base Models

- `from_attributes=True` - Allows creating schemas from SQLAlchemy models
- `alias_generator=to_camel` - Auto camelCase for JSON serialization
- `populate_by_name=True` - Accept both snake_case and camelCase
- `validate_assignment=True` - Validate on attribute assignment
- `use_enum_values=True` - Use enum values instead of enum objects

## Schema Types per Feature

For each feature, create the following schemas:

| Schema | Purpose | Example |
|--------|---------|---------|
| `{Entity}Create` | Input for creation | `UserCreate` - only writable fields |
| `{Entity}` | Internal representation | `User` - all fields |
| `{Entity}Response` | API response | `UserResponse` - fields to expose |
| `{Entity}Update` | Input for updates (PATCH) | `UserUpdate` - updatable fields only |

## Field Definitions

Use `Annotated` with `Field` for validation and documentation:

```python
from typing import Annotated
from pydantic import Field
from ..schemas import AppBaseModelStripped


class UserCreate(AppBaseModelStripped):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["John Doe"],
            description="User's full name",
        ),
    ]
```

## List Responses

Always wrap list responses with `ListResponse[T]` for future extensibility (pagination, metadata):

```python
from ..schemas import ListResponse
from .schemas import UserResponse

# In routes
@router.get("/", response_model=ListResponse[UserResponse])
async def get_all():
    items = await get_all_items(db)
    return ListResponse(data=items)
```

## Example: Complete Schema File

```python
from datetime import datetime
from typing import Annotated

from pydantic import Field

from ..schemas import AppBaseModelStripped


class UserCreate(AppBaseModelStripped):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["John Doe"],
            description="User's full name",
        ),
    ]


class User(AppBaseModelStripped):
    id: Annotated[int, Field(examples=[1], description="User ID")]
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["John Doe"], description="User's full name")]
    created_at: Annotated[datetime, Field(description="Timestamp when user was created")]
    updated_at: Annotated[datetime, Field(description="Timestamp when user was last updated")]


class UserResponse(AppBaseModelStripped):
    id: Annotated[int, Field(examples=[1], description="User ID")]
    name: Annotated[str, Field(min_length=1, max_length=255, examples=["John Doe"], description="User's full name")]
    created_at: Annotated[datetime, Field(description="Timestamp when user was created")]
    updated_at: Annotated[datetime, Field(description="Timestamp when user was last updated")]


class UserUpdate(AppBaseModelStripped):
    name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            examples=["Jane Smith"],
            description="Updated user name",
        ),
    ]
```
