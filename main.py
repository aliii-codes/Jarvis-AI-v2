import sys
import os
import subprocess
import threading
import asyncio
import logging
from time import sleep
from dotenv import dotenv_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from Frontend.GUI import (
    GraphicalUserInterface,
    SetAssistantStatus,
    ShowTextToScreen,
    SetMicrophoneStatus,
    AnswerModifier,
    QueryModifier,
    GetMicrophoneStatus,
    GetAssistantStatus,
    GetCurrentProfile,
)
from Backend.Model import FirstLayerDMW
from Backend.RealtimeSearchEngine import RealtimeSearchEngine
from Backend.Automation import Automation
from Backend.SpeechToText import SpeechRecognition
from Backend.TextToSpeech import TextToSpeech
from Backend.ChatBot import ChatBot

AUTOMATION_FUNCS = ["open", "close", "play", "system", "content", "google search", "youtube search"]
_subprocesses = []

def _get_profile_values():
    profile = GetCurrentProfile()
    if profile:
        username  = profile.get("display_name", "User")
        asst_name = profile.get("settings", {}).get("assistant_name", "Jarvis")
        voice     = profile.get("settings", {}).get("voice", "en-US-JennyNeural")
    else:
        env = dotenv_values(".env")
        username  = env.get("Username", "User")
        asst_name = env.get("Assistantname", "Jarvis")
        voice     = env.get("AssistantVoice", "en-US-JennyNeural")
    return username, asst_name, voice

async def MainExecution():
    username, asst_name, voice = _get_profile_values()

    SetAssistantStatus("Listening...")
    Query = SpeechRecognition()
    if not Query:
        SetAssistantStatus("Available...")
        return False

    ShowTextToScreen(f"{username}: {Query}")
    SetAssistantStatus("Thinking...")
    Decision = FirstLayerDMW(Query)
    logging.info(f"Decision: {Decision}")

    G = any(i.startswith("general") for i in Decision)
    R = any(i.startswith("realtime") for i in Decision)
    Merged = " and ".join(
        " ".join(i.split()[1:]) for i in Decision
        if i.startswith("general") or i.startswith("realtime")
    )

    ImageQuery = next((q for q in Decision if "generate image" in q), None)
    if ImageQuery:
        img_path = os.path.join("Frontend", "Files", "Imagegeneration.data")
        os.makedirs(os.path.dirname(img_path), exist_ok=True)
        try:
            with open(img_path, "w", encoding="utf-8") as f:
                f.write(f"{ImageQuery}, True")
            p = subprocess.Popen(["python", os.path.join("Backend", "ImageGeneration.py")],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
            _subprocesses.append(p)
        except Exception as e:
            logging.error(f"ImageGeneration error: {e}")

    has_automation = any(q.startswith(fn) for q in Decision for fn in AUTOMATION_FUNCS)
    if has_automation:
        await Automation(list(Decision))

    if (G and R) or R:
        SetAssistantStatus("Searching...")
        Answer = RealtimeSearchEngine(QueryModifier(Merged))
        ShowTextToScreen(f"{asst_name}: {Answer}")
        SetAssistantStatus("Answering...")
        TextToSpeech(Answer, voice=voice)
        return True

    for q in Decision:
        if q.startswith("general"):
            SetAssistantStatus("Thinking...")
            Answer = ChatBot(QueryModifier(q.replace("general", "", 1).strip()))
        elif q.startswith("realtime"):
            SetAssistantStatus("Searching...")
            Answer = RealtimeSearchEngine(QueryModifier(q.replace("realtime", "", 1).strip()))
        elif q.strip() == "exit":
            Answer = ChatBot(QueryModifier("Okay, Bye!"))
            ShowTextToScreen(f"{asst_name}: {Answer}")
            TextToSpeech(Answer, voice=voice)
            for p in _subprocesses:
                p.terminate()
            sys.exit(0)
        else:
            continue

        ShowTextToScreen(f"{asst_name}: {Answer}")
        SetAssistantStatus("Answering...")
        TextToSpeech(Answer, voice=voice)
        return True

    return False

def BackendThread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        if GetMicrophoneStatus() == "True":
            loop.run_until_complete(MainExecution())
        elif "available" not in GetAssistantStatus().lower():
            SetAssistantStatus("Available...")
        sleep(0.1)

if __name__ == "__main__":
    os.makedirs("Data", exist_ok=True)
    SetMicrophoneStatus("False")
    SetAssistantStatus("Available...")

    t = threading.Thread(target=BackendThread, daemon=True)
    t.start()
    GraphicalUserInterface()