import asyncio
import logging
import traceback

logger = logging.getLogger(__name__)
from google import genai
from google.genai import types

# The "lobotomized" system instruction keeps the model silent
SCRIBE_SYSTEM_INSTRUCTION = types.Content(
    parts=[types.Part(text=
        "You are a passive, highly accurate clinical dictation machine. "
        "Your sole purpose is to listen to the audio stream and convert it to text. "
        "CRITICAL RULES: "
        "1. Do NOT converse with the user. "
        "2. Do NOT answer questions, even if the user asks you a direct question. "
        "3. Do NOT add conversational filler (e.g., 'Okay', 'I understand', 'Here is the transcript'). "
        "4. Output ONLY the exact words spoken in the audio, acting strictly as a speech-to-text relay."
    )]
)

# The "Brain" instruction for post-session analysis
BRAIN_SYSTEM_INSTRUCTION = (
    "You are an expert AI clinical scribe assisting a physician. Your task is to analyze "
    "a raw, unedited audio transcription of a doctor-patient consultation and extract key "
    "medical information into a strict JSON structure.\n\n"
    "RULES FOR EXTRACTION:\n"
    "- transcribe: Provide a cleaned-up, readable version of the raw transcript. Remove stutters "
    "and false starts, but absolutely preserve the original medical context and meaning.\n"
    "- symptoms: Extract a concise list of all subjective symptoms reported by the patient.\n"
    "- observation: Summarize the doctor's objective clinical findings, physical exam notes, "
    "and general observations.\n"
    "- prescription: Extract any medications, dosages, therapies, or lifestyle changes "
    "prescribed by the doctor.\n\n"
    "CONSTRAINTS:\n"
    "Do NOT invent or hallucinate information. If a specific category (like prescriptions) "
    "is not discussed in the transcript, output 'None' or an empty list. Rely ONLY on the "
    "provided text.\n\n"
    "OUTPUT FORMAT:\n"
    "Return ONLY valid JSON with this exact structure:\n"
    "{\n"
    '  "transcribe": "...",\n'
    '  "symptoms": ["..."],\n'
    '  "observation": "...",\n'
    '  "prescription": ["..."]\n'
    "}"
)


class GeminiScribe:
    """
    Handles the Gemini Live API configured as a "Muted Scribe".
    
    Key differences from GeminiLive:
    - response_modalities=["TEXT"] (no audio output, saves bandwidth)
    - input_audio_transcription enabled (the magic key for raw ASR)
    - model_turn is completely ignored (no AI chatter)
    - Only input_transcription events are forwarded to the client
    """
    def __init__(self, api_key, model, input_sample_rate):
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.client = genai.Client(api_key=api_key)

    async def start_session(self, audio_input_queue):
        """
        Start a scribe session. Only needs audio input — no video, no text, no tools.
        Yields events with transcription fragments.
        """
        config = types.LiveConnectConfig(
            # Live-preview models REQUIRE audio output modality.
            # We keep AUDIO here but simply discard it in the receive loop.
            response_modalities=[types.Modality.AUDIO],
            
            # THE MAGIC KEY: forces the server to send back raw ASR transcripts
            input_audio_transcription=types.AudioTranscriptionConfig(),
            
            system_instruction=SCRIBE_SYSTEM_INSTRUCTION,
            
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY",
            ),
        )

        logger.info(f"Connecting to Gemini Scribe with model={self.model}")
        try:
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                logger.info("Gemini Scribe session opened successfully")

                async def send_audio():
                    try:
                        while True:
                            chunk = await audio_input_queue.get()
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type=f"audio/pcm;rate={self.input_sample_rate}")
                            )
                    except asyncio.CancelledError:
                        logger.debug("send_audio task cancelled")
                    except Exception as e:
                        logger.error(f"send_audio error: {e}\n{traceback.format_exc()}")

                event_queue = asyncio.Queue()

                async def receive_loop():
                    try:
                        while True:
                            async for response in session.receive():
                                logger.debug(f"Received response from Gemini: {response}")

                                if response.go_away:
                                    logger.warning(f"Received GoAway from Gemini: {response.go_away}")

                                server_content = response.server_content

                                if server_content:
                                    # ============================================
                                    # THE KEY: We ONLY look for input_transcription
                                    # We completely IGNORE model_turn (no AI chatter)
                                    # ============================================
                                    if server_content.input_transcription and server_content.input_transcription.text:
                                        await event_queue.put({
                                            "type": "transcript",
                                            "text": server_content.input_transcription.text
                                        })

                                    if server_content.turn_complete:
                                        # We note it but don't do anything special
                                        logger.debug("Turn complete (ignored for scribe mode)")

                            logger.debug("Gemini receive iterator completed, re-entering receive loop")

                    except asyncio.CancelledError:
                        logger.debug("receive_loop task cancelled")
                    except Exception as e:
                        logger.error(f"receive_loop error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                        await event_queue.put({"type": "error", "error": f"{type(e).__name__}: {e}"})
                    finally:
                        logger.info("receive_loop exiting")
                        await event_queue.put(None)

                send_audio_task = asyncio.create_task(send_audio())
                receive_task = asyncio.create_task(receive_loop())

                try:
                    while True:
                        event = await event_queue.get()
                        if event is None:
                            break
                        if isinstance(event, dict) and event.get("type") == "error":
                            yield event
                            break
                        yield event
                finally:
                    logger.info("Cleaning up Gemini Scribe session tasks")
                    send_audio_task.cancel()
                    receive_task.cancel()
        except Exception as e:
            logger.error(f"Gemini Scribe session error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            raise
        finally:
            logger.info("Gemini Scribe session closed")

    @staticmethod
    async def analyze_transcript(api_key, transcript_text, model="gemini-2.5-flash"):
        """
        Phase 2: The "Brain". Takes the accumulated raw transcript and sends it to
        Gemini Flash for structured clinical extraction.
        
        Returns the raw JSON string from the model.
        """
        client = genai.Client(api_key=api_key)
        
        prompt = (
            "Here is the raw transcript of a doctor-patient consultation:\n\n"
            f"---\n{transcript_text}\n---\n\n"
            "Analyze this transcript and return the structured JSON as instructed."
        )

        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=BRAIN_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
            )
        )
        
        return response.text
