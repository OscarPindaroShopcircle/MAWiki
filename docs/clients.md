# External Service Client Conventions

## Overview

The `src/backend/clients/` folder contains wrappers for external services and third-party libraries. Clients provide a clean abstraction layer that encapsulates:

- Authentication and credential management
- Request/response handling
- Error handling and retries
- Rate limiting
- Logging and monitoring

## When to Create a Client

Create a client when you need to integrate with:

- **Third-party APIs** - Payment processors (Stripe, PayPal), email services (SendGrid, Mailgun), SMS providers (Twilio)
- **AI/ML services** - OpenAI, Anthropic, Hugging Face
- **Cloud services** - AWS S3, Google Cloud Storage, Azure Blob Storage
- **External dependencies** - Search engines (Elasticsearch, Algolia), analytics platforms, monitoring services

## Client Structure

Each client should be a self-contained module:

```
src/backend/clients/
├── openai_client.py
├── stripe_client.py
├── s3_client.py
└── email_client.py
```

## Client Pattern

### Basic Client Template

```python
from typing import Any
import httpx
from ..config import settings


class ExternalServiceClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or settings.external_service_api_key
        self.base_url = base_url or settings.external_service_base_url
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def close(self):
        await self.client.aclose()

    async def make_request(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self.client.post(endpoint, json=data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ExternalServiceError(f"API request failed: {e.response.status_code}")
        except httpx.RequestError as e:
            raise ExternalServiceError(f"Request error: {str(e)}")


class ExternalServiceError(Exception):
    pass
```

### Dependency Injection Pattern

Create a dependency function for FastAPI routes:

```python
from typing import Annotated
from fastapi import Depends

async def get_external_service_client() -> ExternalServiceClient:
    client = ExternalServiceClient()
    try:
        yield client
    finally:
        await client.close()

ClientDep = Annotated[ExternalServiceClient, Depends(get_external_service_client)]
```

Usage in routes:

```python
@router.post("/process")
async def process_data(
    data: RequestData,
    client: ClientDep,
):
    result = await client.make_request("/process", data.model_dump())
    return result
```

## Best Practices

### 1. Configuration Management

Store credentials and configuration in `config.py`, never hardcode:

```python
class Settings(BaseSettings):
    openai_api_key: str = Field(..., description="OpenAI API key")
    stripe_api_key: str = Field(..., description="Stripe API key")
    s3_bucket_name: str = Field(..., description="S3 bucket name")
```

### 2. Error Handling

Create specific exception classes for different error types:

```python
class ClientError(Exception):
    pass

class AuthenticationError(ClientError):
    pass

class RateLimitError(ClientError):
    pass

class ServiceUnavailableError(ClientError):
    pass
```

### 3. Retry Logic

Implement retry logic for transient failures:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class ResilientClient:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def make_request(self, endpoint: str, data: dict[str, Any]):
        # Implementation
        pass
```

### 4. Logging

Log all external API calls for debugging and monitoring:

```python
import logging

logger = logging.getLogger(__name__)

async def make_request(self, endpoint: str, data: dict[str, Any]):
    logger.info(f"Making request to {endpoint}", extra={"data": data})
    try:
        response = await self.client.post(endpoint, json=data)
        logger.info(f"Request successful: {response.status_code}")
        return response.json()
    except Exception as e:
        logger.error(f"Request failed: {str(e)}", exc_info=True)
        raise
```

### 5. Type Safety

Use Pydantic models for request/response validation:

```python
from pydantic import BaseModel

class ExternalServiceRequest(BaseModel):
    query: str
    max_results: int = 10

class ExternalServiceResponse(BaseModel):
    results: list[dict[str, Any]]
    total: int

async def search(self, request: ExternalServiceRequest) -> ExternalServiceResponse:
    response = await self.make_request("/search", request.model_dump())
    return ExternalServiceResponse(**response)
```

## Testing Clients

### Unit Tests with Mocking

```python
from unittest.mock import AsyncMock, patch
import pytest

@pytest.mark.asyncio
async def test_client_success():
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value.json.return_value = {"status": "success"}
        mock_post.return_value.status_code = 200

        client = ExternalServiceClient()
        result = await client.make_request("/test", {})

        assert result["status"] == "success"
```

### Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_api_call():
    client = ExternalServiceClient(api_key="test_key")

    result = await client.make_request("/test", {"query": "test"})

    assert "results" in result
    await client.close()
```

## Example: OpenAI Client

```python
from openai import AsyncOpenAI
from ..config import settings


class OpenAIClient:
    def __init__(self, api_key: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)

    async def create_completion(
        self,
        prompt: str,
        model: str = "gpt-4",
        max_tokens: int = 1000,
    ) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise OpenAIError(f"OpenAI API error: {str(e)}")


class OpenAIError(Exception):
    pass


async def get_openai_client() -> OpenAIClient:
    return OpenAIClient()
```

## Checklist

When creating a new client:

- [ ] Client class created in `src/backend/clients/`
- [ ] Configuration added to `config.py` for credentials and settings (even tough sometimes credentials can be stored in a DB, or there are multiple credentials for the same service)
- [ ] Custom exception classes defined for error handling
- [ ] Async context manager support (`__aenter__`, `__aexit__`)
- [ ] Proper resource cleanup (close connections)
- [ ] Retry logic for transient failures
- [ ] Logging for all external calls
- [ ] Type hints and Pydantic models for requests/responses
- [ ] Dependency injection function for FastAPI routes
- [ ] Unit tests with mocked responses
- [ ] Integration tests (optional, for critical clients)
