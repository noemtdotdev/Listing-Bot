import aiohttp
from typing import Optional
import json
import os
from api.auth_utils import API_KEY
from dotenv import load_dotenv

load_dotenv()

PARENT_API_HOST = os.getenv("PARENT_API_HOST", "127.0.0.1")
PARENT_API_PORT = os.getenv("PARENT_API_PORT", "7000")
BOT_SERVICE_HOST = os.getenv("BOT_SERVICE_HOST", "127.0.0.1")

ports = {
    "nom": 49089,
}

class APIProxyManager:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

        self.base_url = f"http://{PARENT_API_HOST}:{PARENT_API_PORT}"

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    async def get(self, endpoint: str, params: dict = None):
        url = f"{self.base_url}/{endpoint}"
        async with self.session.get(url, params=params) as response:
            response.raise_for_status()
            return await response.json()
        
    async def post(self, endpoint: str, data: dict = None):
        url = f"{self.base_url}/{endpoint}"
        async with self.session.post(url, json=data) as response:
            response.raise_for_status()
            return await response.json()
        
    async def put(self, endpoint: str, data: dict = None):
        url = f"{self.base_url}/{endpoint}"
        async with self.session.put(url, json=data) as response:
            response.raise_for_status()
            return await response.json()
        
    async def delete(self, endpoint: str):
        url = f"{self.base_url}/{endpoint}"
        async with self.session.delete(url) as response:
            response.raise_for_status()
            return await response.json()

        
class BotCommunicator:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.close()

    def fetch_ports(self) -> dict:
        if os.path.exists("../parent_api/ports.json"):
            with open("../parent_api/ports.json", "r") as f:
                return json.load(f)
        return ports

    async def request(self, endpoint: str, request_type: str = "GET", bots: Optional[list[str]] = None, data: Optional[dict] = None, **kwargs):
        ports = self.fetch_ports()
        ports_to_request = [ports.get(bot) for bot in bots] if bots else ports.values()
        cleaned_ports = [port for port in ports_to_request if port is not None]

        for port in cleaned_ports:
            url = f"http://{BOT_SERVICE_HOST}:{port}/{endpoint}?api_key={API_KEY}"

            if request_type == "GET":
                async with self.session.get(url, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
            elif request_type == "POST":
                async with self.session.post(url, json=data, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
            elif request_type == "PUT":
                async with self.session.put(url, json=data, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
            elif request_type == "DELETE":
                async with self.session.delete(url, **kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
