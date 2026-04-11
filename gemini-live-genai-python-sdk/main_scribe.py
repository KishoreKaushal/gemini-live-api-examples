import asyncio
import json
import logging
import os
import traceback

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from gemini_scribe import GeminiScribe

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("gemini_scribe").setLevel(logging.DEBUG)
logging.getLogger(__name__).setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("MODEL", "gemini-3.1-flash-live-preview")

# Initialize FastAPI
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files from the scribe frontend
app.mount("/static", StaticFiles(directory="frontend_scribe"), name="static")


@app.get("/")
async def root():
    return FileResponse("frontend_scribe/index.html")


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/api/analyze")
async def analyze_transcript(req: AnalyzeRequest):
    """
    Phase 2: The "Brain" endpoint.
    Takes the accumulated raw transcript and returns structured clinical JSON.
    """
    logger.info(f"Analyzing transcript ({len(req.transcript)} chars)")
    try:
        result = await GeminiScribe.analyze_transcript(
            api_key=GEMINI_API_KEY,
            transcript_text=req.transcript,
        )
        # The result should be valid JSON string from Gemini
        try:
            parsed = json.loads(result)
            return {"status": "ok", "data": parsed}
        except json.JSONDecodeError:
            # If Gemini didn't return valid JSON, return the raw text
            return {"status": "ok", "data": {"raw": result}}
    except Exception as e:
        logger.error(f"Analysis error: {e}\n{traceback.format_exc()}")
        return {"status": "error", "error": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for the Muted Scribe session."""
    await websocket.accept()
    logger.info("Scribe WebSocket connection accepted")

    audio_input_queue = asyncio.Queue()

    scribe = GeminiScribe(
        api_key=GEMINI_API_KEY, model=MODEL, input_sample_rate=16000
    )

    async def receive_from_client():
        try:
            while True:
                message = await websocket.receive()
                if message.get("bytes"):
                    await audio_input_queue.put(message["bytes"])
                # We ignore text messages in scribe mode
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error receiving from client: {e}")

    receive_task = asyncio.create_task(receive_from_client())

    async def run_session():
        async for event in scribe.start_session(
            audio_input_queue=audio_input_queue,
        ):
            if event:
                # Forward transcript events to client as JSON
                await websocket.send_json(event)

    try:
        await run_session()
    except Exception as e:
        logger.error(f"Error in Scribe session: {type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        receive_task.cancel()
        try:
            await websocket.close()
        except:
            pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="localhost", port=port)
