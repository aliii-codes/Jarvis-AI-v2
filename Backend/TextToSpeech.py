import pygame
import random
import asyncio
import edge_tts
import os
import logging
from dotenv import dotenv_values

env_vars = dotenv_values(".env")
_DEFAULT_VOICE = env_vars.get("AssistantVoice", "en-US-JennyNeural")

_SPEECH_PATH = os.path.join("Data", "speech.mp3")
os.makedirs("Data", exist_ok=True)

pygame.mixer.init()

_OVERFLOW_RESPONSES = [
    "The rest of the answer is on the chat screen.",
    "Check the chat screen for the full response.",
    "More details are shown on the chat screen.",
    "See the chat screen for the complete answer.",
]

async def _synthesize(text: str, voice: str) -> None:
    if os.path.exists(_SPEECH_PATH):
        os.remove(_SPEECH_PATH)
    communicate = edge_tts.Communicate(text, voice, pitch="+5Hz", rate="+5%")
    await communicate.save(_SPEECH_PATH)

def _play(stop_func) -> None:
    pygame.mixer.music.load(_SPEECH_PATH)
    pygame.mixer.music.play()
    clock = pygame.time.Clock()
    while pygame.mixer.music.get_busy():
        if stop_func():
            pygame.mixer.music.stop()
            break
        clock.tick(15)

def TextToSpeech(text: str, voice: str = None, stop_func=lambda: False) -> bool:
    voice = voice or _DEFAULT_VOICE
    sentences = [s.strip() for s in str(text).split(".") if s.strip()]
    speak_text = text
    if len(sentences) > 4 and len(text) > 250:
        speak_text = ". ".join(sentences[:2]) + ". " + random.choice(_OVERFLOW_RESPONSES)
    try:
        asyncio.run(_synthesize(speak_text, voice))
        _play(stop_func)
        return True
    except Exception as e:
        logging.error(f"TTS error: {e}")
        return False

if __name__ == "__main__":
    while True:
        TextToSpeech(input("Enter text: "))




