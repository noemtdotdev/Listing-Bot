from typing import Tuple, Dict
from .errors import ApiError, MojangError
from discord import Webhook
from .constants import api_key
import aiohttp
import requests
import os
from dotenv import load_dotenv

load_dotenv()

PARENT_API_HOST = os.getenv("PARENT_API_HOST", "127.0.0.1")
PARENT_API_PORT = os.getenv("PARENT_API_PORT", "7000")
SKYBLOCK_API_HOST = os.getenv("SKYBLOCK_API_HOST", "127.0.0.1")
SKYBLOCK_API_PORT = os.getenv("SKYBLOCK_API_PORT", "3002")

def handle_selection(selection):
    """
    Returns the cute name of the selected profile.
    """

    if selection is None:
        return None

    if any(icon in selection for icon in ["🎲", "♻", "🏝"]):
        return selection[:-2].strip()

    return selection.strip()


async def fetch_mojang_api(session: aiohttp.ClientSession, username):
    async def fetch_data(url):
        async with session.get(url) as response:
            try:
                return await response.json(), response.status
            except:
                return {}, response.status

    url = f"https://mowojang.matdoes.dev/{username.replace('-', '')}"
    data, status = await fetch_data(url)
    if status == 200:
        return {
            "name": data.get("name", "Invalid Username."),
            "id": data.get("id", "Invalid Username.").replace("-", ""),
        }, status

    # If Mojang API request fails, return error
    return {"id": "Invalid username.", "name": "Invalid username."}, status

def validate_uuid(uuid: str) -> bool:
    # should handle both with and without hyphens
    uuid = uuid.replace("-", "")
    if len(uuid) != 32:
        return False
    try:
        int(uuid, 16)
        return True
    except ValueError:
        return False
    
async def fetch_profile_data(session, uuid, bot, profile=None, allow_error_handler=True) -> Tuple[Dict, str]:

    if not validate_uuid(uuid) and len(uuid) > 16:
        if allow_error_handler:
            raise MojangError("Invalid UUID or Username")
        else:
            return None, None

    word = "profile" if profile else "profiles"
    if profile:
        profile = profile.strip()
    
    if not len(uuid) > 16:
        mojang_data = await fetch_mojang_api(session, uuid)
        if mojang_data[1] != 200:
            if allow_error_handler:
                raise MojangError("Invalid UUID or Username")
            else:
                return None, None
        uuid = mojang_data[0]["id"]

    try:
        await session.post(f"http://{PARENT_API_HOST}:{PARENT_API_PORT}/live/data-fetch", json={"uuid": uuid})
    except Exception as e:
        pass

    url = f"http://{SKYBLOCK_API_HOST}:{SKYBLOCK_API_PORT}/v1/{word}/{uuid}/{handle_selection(profile) or ''}?key=API_KEY"
    async with session.get(url) as resp:
        profile_data = await resp.json()
        data = profile_data.get("data", {})

    if profile_data.get("status") != 200:
        if allow_error_handler:
            raise ApiError(profile_data.get("reason", profile_data.get("message", "An unknown error occurred.")))
        else:
            return None, None
    
    return data, data.get("name")

async def fetch_raw_hypixel_stats(self, uuid):
    async with aiohttp.ClientSession() as session:
        cached_data = self.bot.get_cached_data(f"player:{uuid}")
        if cached_data:
            data = cached_data
        else:
            # Log the data fetch to the new endpoint with just the UUID
            try:
                await session.post(f"http://{PARENT_API_HOST}:{PARENT_API_PORT}/live/data-fetch", json={"uuid": uuid})
            except Exception as e:
                pass
                
            url = f"https://api.hypixel.net/v2/player?key={api_key}&uuid="+uuid
            async with session.get(url) as r:
                data: dict = await r.json()
                self.bot.cache_data(f"player:{uuid}", data)

    return data

class MojangObject:
    def __init__(self, _input):
        try:
            if len(_input) > 16:
                url = f"https://sessionserver.mojang.com/session/minecraft/profile/{_input.replace('-', '')}"
            else:
                url = f"https://api.mojang.com/users/profiles/minecraft/{_input}"

            api = requests.get(url)
            data = api.json()
            if api.status_code == 200:
                self.name = data.get("name", "Invalid Username.")
                self.uuid = data.get("id", "Invalid Username.").replace("-", "")
            else:
                raise MojangError("Invalid UUID or Username")
        except:
            raise MojangError("Invalid UUID or Username")