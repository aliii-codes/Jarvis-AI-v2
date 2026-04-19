import speech_recognition as sr
from groq import Groq
from dotenv import dotenv_values
import tempfile
import os
import logging

# Load environment variables
env_vars = dotenv_values(".env")
GroqAPIKey = env_vars.get("GroqAPIKey")
InputLanguage = env_vars.get("InputLanguage", "en")  # Default to English

# Initialize Groq client
client = Groq(api_key=GroqAPIKey)

# Initialize speech recognition
recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.8

def SpeechRecognition() -> str | None:
    """Record from mic; transcribe via Groq Whisper with Google STT fallback."""
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            logging.info("Microphone listening...")
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=20)
    except sr.WaitTimeoutError:
        logging.debug("Listen timeout — no speech detected.")
        return None
    except OSError as e:
        logging.error(f"Microphone not accessible: {e}")
        return None

    tmp_path = None
    try:
        wav_data = audio.get_wav_data()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_data)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(tmp_path), f.read()),
                model="whisper-large-v3",
                language=InputLanguage,
            )
        text = result.text.strip()
        logging.info(f"Groq Whisper: {text}")
        return text or None

    except Exception as e:
        logging.warning(f"Groq Whisper failed ({e}), trying Google STT...")
        try:
            text = recognizer.recognize_google(audio, language=InputLanguage)
            logging.info(f"Google STT: {text}")
            return text
        except Exception as e2:
            logging.error(f"Google STT also failed: {e2}")
            return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

if __name__ == "__main__":
    while True:
        result = SpeechRecognition()
        if result:
            print(f"You said: {result}")