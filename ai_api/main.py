import os
import json
import base64
from fastapi.params import Query
from google import genai
from google.genai import types
from dotenv import load_dotenv
from typing import List, Union, Optional, Dict, Any
import fastapi
from fastapi import UploadFile, WebSocket, WebSocketDisconnect
import pathlib
import tempfile
import uvicorn
import mimetypes

app = fastapi.FastAPI(redoc_url=None, docs_url=None)

load_dotenv()

SERVER_API_KEY = os.environ.get("API_KEY")
if not SERVER_API_KEY:
    raise ValueError("API_KEY for endpoint security is not set in the environment.")

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

#MODEL_NAME = "gemini-2.0-flash-lite"
MODEL_NAME = "gemma-3-27b-it"

async def process_input(text_input: str, file_inputs: Optional[List[Union[str, UploadFile, pathlib.Path, Dict[str, Any]]]] = None) -> dict:

    if not isinstance(text_input, str):
        raise TypeError("text_input must be a string")
    
    result = {
        "text_content": text_input,
        "file_parts": []
    }
    
    if file_inputs:
        if not isinstance(file_inputs, list):
            file_inputs = [file_inputs]
            
        for input_item in file_inputs:
            file_bytes = None
            filename = "unknown"
            
            if isinstance(input_item, dict) and 'filename' in input_item and 'content' in input_item:
                filename = input_item['filename']
                file_bytes = base64.b64decode(input_item['content'])
            
            elif isinstance(input_item, UploadFile):
                filename = input_item.filename
                file_bytes = await input_item.read()
            
            elif isinstance(input_item, (str, pathlib.Path)):
                path_str = str(input_item)
                if os.path.exists(path_str):
                    filename = os.path.basename(path_str)
                    with open(path_str, 'rb') as f:
                        file_bytes = f.read()
                else:
                    raise FileNotFoundError(f"File not found: {path_str}")
            
            else:
                raise TypeError(f"Unsupported input type in file_inputs: {type(input_item)}")

            if file_bytes:
                mime_type, _ = mimetypes.guess_type(filename)
                if mime_type is None:
                    mime_type = 'application/octet-stream'
                
                result["file_parts"].append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    
    return result

@app.websocket("/ws/process/")
async def websocket_process(websocket: WebSocket, api_key: Optional[str] = Query(None)):
    await websocket.accept()

    if api_key != SERVER_API_KEY:
        await websocket.send_json({
            "status": "error",
            "error": "Invalid or missing API Key.",
            "finished": True
        })
        await websocket.close(code=1008)
        return
    
    try:
        data = await websocket.receive_json()
        await websocket.send_json({"status": "processing"})
        
        text_input = data.get("text_input", "")
        file_inputs = data.get("files", [])
        
        processed_data = await process_input(text_input, file_inputs)
        
        await websocket.send_json({"status": "generating_response"})
        
        contents = [processed_data["text_content"]] + processed_data["file_parts"]
        
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=contents
        )
        
        await websocket.send_json({
            "status": "complete", 
            "response": response.text,
            "finished": True
        })
        
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        await websocket.send_json({
            "status": "error",
            "error": str(e),
            "finished": True
        })

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=2)