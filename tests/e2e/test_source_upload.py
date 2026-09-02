import uuid
from collections.abc import Generator

import httpx
import pytest

from src.backend.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from src.backend.config import AppConfig
from src.backend.sources.schemas import SourceCreate, SourceResponse

pytestmark = pytest.mark.e2e


@pytest.fixture
def backend_url(app_config: AppConfig) -> str:
    return f"http://{app_config.backend_host}:{app_config.backend_port}"


@pytest.fixture
def e2e_client(backend_url: str) -> Generator[httpx.Client, None, None]:
    with httpx.Client(base_url=backend_url, timeout=30) as client:
        yield client


@pytest.fixture
def registration() -> RegisterRequest:
    return RegisterRequest(
        name="E2E Admin",
        email="e2e-admin@example.com",
        password="e2e-password",
    )


@pytest.fixture
def source() -> SourceCreate:
    return SourceCreate(name="Upload E2E")


def test_source_file_upload_endpoint(
    e2e_client: httpx.Client,
    registration: RegisterRequest,
    source: SourceCreate,
) -> None:
    response = e2e_client.post(
        "/auth/register",
        json=registration.model_dump(mode="json"),
    )
    if response.status_code != 200:
        login = LoginRequest(email=registration.email, password=registration.password)
        response = e2e_client.post(
            "/auth/login",
            json=login.model_dump(mode="json"),
        )
    assert response.status_code == 200, response.text

    tokens = TokenResponse.model_validate(response.json())
    headers = {"Authorization": f"Bearer {tokens.access_token}"}
    response = e2e_client.post(
        "/api/sources/",
        json=source.model_dump(mode="json", by_alias=True),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    created = SourceResponse.model_validate(response.json())

    try:
        file_id = uuid.uuid4()
        content = b"uploaded through the HTTP endpoint"
        response = e2e_client.post(
            f"/sources/{created.id}/files",
            data={"file_ids": str(file_id)},
            files={"files": ("endpoint.txt", content, "text/plain")},
            headers=headers,
        )
        assert response.status_code == 204, response.text

        response = e2e_client.get(
            f"/api/sources/{created.id}/files/{file_id}/download",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.content == content
    finally:
        e2e_client.delete(f"/api/sources/{created.id}", headers=headers)
