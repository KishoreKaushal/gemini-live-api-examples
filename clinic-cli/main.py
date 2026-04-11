import asyncio
import sys
from dotenv import load_dotenv
from google import genai

load_dotenv()
from google.genai import types
import pyaudio

# pyaudio config
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 1024

client = genai.Client()
MODEL = "gemini-2.5-flash"

CONFIG = {
    "response_modalities": ["TEXT"],
    "system_instruction": types.Content(parts=[types.Part(text=
        "You are a passive clinical note-taker. "
        "Listen to the ongoing conversation. Do not respond or say anything while the conversation is ongoing. "
        "When you receive the exact text message 'CONVERSATION_ENDED', you must output ONLY a JSON object representing the clinical summary. "
        "The JSON MUST follow this schema strictly:\n"
        "{\n"
        '  "transcribe": "The complete, raw transcription of the conversation.",\n'
        '  "symptoms": "Symptoms as described by the patient.",\n'
        '  "observation": "Observations and assessments as described by the doctor.",\n'
        '  "prescription": "Any prescriptions, medications, or plan mentioned by the doctor."\n'
        "}\n"
        "Do not include markdown formatting blocks (like ```json), just output the raw JSON string."
    )])
}

class LiveClinicalCLI:
    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.audio_stream = None
        self.is_recording = False
        self.mic_task = None
        self.receive_task = None
        self.final_json = ""
        self.session = None
        self.summary_ready = asyncio.Event()

    async def _mic_loop(self):
        try:
            mic_info = self.p.get_default_input_device_info()
            self.audio_stream = await asyncio.to_thread(
                self.p.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                input_device_index=mic_info["index"],
                frames_per_buffer=CHUNK,
            )
            
            kwargs = {"exception_on_overflow": False} if __debug__ else {}
            while self.is_recording:
                data = await asyncio.to_thread(self.audio_stream.read, CHUNK, **kwargs)
                if self.session:
                    await self.session.send_realtime_input(audio={"data": data, "mime_type": "audio/pcm"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Mic error: {e}")
        finally:
            if self.audio_stream:
                self.audio_stream.stop_stream()
                self.audio_stream.close()

    async def _receive_loop(self):
        try:
            while True:
                async for response in self.session.receive():
                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.text:
                                self.final_json += part.text
                                
                    if response.server_content and response.server_content.turn_complete:
                        # If we have received the end signal and the turn is complete, we are done
                        if not self.is_recording:
                            self.summary_ready.set()
                            
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Receive error: {e}")

    async def start(self):
        async with client.aio.live.connect(model=MODEL, config=CONFIG) as session:
            self.session = session
            print("🎙️ Connected! Recording started... (Press ENTER to stop)")
            
            self.is_recording = True
            self.mic_task = asyncio.create_task(self._mic_loop())
            self.receive_task = asyncio.create_task(self._receive_loop())
            
            # Wait for user to press ENTER
            await asyncio.to_thread(input)
            
            print("\n🛑 Recording stopped. Requesting summary from Gemini...")
            self.is_recording = False
            self.mic_task.cancel()
            
            # Send the end signal using text
            await session.send(input="CONVERSATION_ENDED. Please provide the JSON summary now.", end_of_turn=True)
            
            # Wait for the model to finish generating the JSON response
            await asyncio.wait_for(self.summary_ready.wait(), timeout=30.0)
            
            self.receive_task.cancel()
            
            print("\n=== 📝 Clinical Summary JSON ===")
            print(self.final_json.strip())
            print("================================")
            
        self.p.terminate()

def main():
    cli = LiveClinicalCLI()
    try:
        input("Press ENTER to connect and start the clinical recording...")
        asyncio.run(cli.start())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        
if __name__ == "__main__":
    main()
