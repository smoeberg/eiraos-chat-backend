import pytest
import asyncio
from eiraos.client.sdk import EiraOSClient

@pytest.mark.asyncio
async def test_sdk_client_workflow():
    client = EiraOSClient(base_url="http://localhost:8000/api/v1")
    # Verify client initializes correctly
    assert client.base_url == "http://localhost:8000/api/v1"
    assert client.token is None
