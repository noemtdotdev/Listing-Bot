# This file is supposed to be turned into a package.

import asyncio
import json
import base64
import websockets
import aiohttp
import time
import os
from urllib.parse import urlparse
from typing import List, Optional, Dict, Any, Union

class AIResponse:
    def __init__(self, raw_response: Optional[Dict[str, Any]], total_time: float):
        self._raw_response = raw_response if raw_response else {}
        self.total_time_seconds = round(total_time, 2)

    @property
    def raw_data(self) -> Any:
        return self._raw_response.get("response")

    def parse(self) -> Union[Dict, str, Any]:
        data = self.raw_data
        if not isinstance(data, str):
            return data

        cleaned_data = data.strip()

        if cleaned_data.startswith("```json") and cleaned_data.endswith("```"):
            cleaned_data = cleaned_data[7:-3].strip()
        
        try:
            return json.loads(cleaned_data)
        except json.JSONDecodeError:
            return cleaned_data

    def __repr__(self):
        return f"<AIResponse time={self.total_time_seconds}s>"

server_ip = ""

async def ask_ai(
    bot,
    text_input: str,
    file_paths: Optional[List[str]] = None,
    return_json: bool = True,
) -> AIResponse:
    start_time = time.time()
    websocket_url = f"ws://{server_ip}:2/ws/process/?api_key=API_KEY"
    # ai_api\.env.example (this api key)

    if bot is None:
        raise ValueError("Bot instance is required to access AI configuration.")
    
    ai_config = await bot.db.fetchone("SELECT * FROM ai_config")
    if ai_config is None:
        raise ValueError("AI configuration not found in the database.")
    
    free_credits = ai_config[1]
    paid_credits = ai_config[2]
    
    if free_credits <= 0 and paid_credits <= 0:
        raise ValueError("No AI credits available. Please check your AI configuration.")
    
    files = []
    if file_paths:
        async with aiohttp.ClientSession() as session:
            for path_or_url in file_paths:
                try:
                    if path_or_url.lower().startswith(('http://', 'https://')):
                        async with session.get(path_or_url) as response:
                            response.raise_for_status()
                            file_content = await response.read()
                            filename = os.path.basename(urlparse(path_or_url).path)
                    else:
                        with open(path_or_url, 'rb') as file:
                            file_content = file.read()
                        filename = os.path.basename(path_or_url)
                    
                    b64_content = base64.b64encode(file_content).decode('utf-8')
                    files.append({
                        'filename': filename,
                        'content': b64_content
                    })
                except Exception as e:
                    pass
    
    prompt = text_input
    if return_json:
        prompt += "\nReturn the data in PLAIN JSON, NO FORMATTING, NO MARKDOWN, no text, just JSON."

    payload = {
        "text_input": prompt,
        "files": files
    }
    
    final_response = None
    
    async with websockets.connect(websocket_url) as websocket:
        await websocket.send(json.dumps(payload))
        
        while True:
            response_text = await websocket.recv()
            response = json.loads(response_text)
            
            if response.get("finished"):
                final_response = response
                break
    
    end_time = time.time()
    total_time = end_time - start_time

    if final_response is None:
        raise ValueError("No response received from the AI service.")
    
    if free_credits > 0:
        await bot.db.execute("UPDATE ai_config SET remaining_credits_free = remaining_credits_free - 1")
    else:
        await bot.db.execute("UPDATE ai_config SET remaining_credits_paid = remaining_credits_paid - 1")

    await bot.db.execute(
        "INSERT INTO ai_calls (call_type, response_time_ms, input_tokens, output_tokens, response_text) VALUES (?, ?, ?, ?, ?)",
        "text_input", int(total_time * 1000), len(text_input)//4, len(final_response.get("response", ""))//4, final_response.get("response", "")
    )

    return AIResponse(raw_response=final_response, total_time=total_time)

# keep in mind this is BOUND to the way my bots are written and any changes to the database may require changing this.