# Important Libraries
from AppOpener import close, open as appopen
from webbrowser import open as webopen
from pywhatkit import search, playonyt
from dotenv import dotenv_values
from bs4 import BeautifulSoup
from rich import print
from groq import Groq
import webbrowser
import subprocess
import requests
import keyboard
import asyncio
import os

# Load environment variables
env_vars = dotenv_values(".env")
GroqAPIKey = env_vars.get("GroqAPIKey")

# Google search related settings
classes = [
    "C2Wbwf", "hgKElc", "LTKOO sY7ric", "Z0LCwf", "gsrt vk_bFzWSb YwPhnf",
    "pclqee", "tw-Data-text tw-text-small tw-ta", "IZ76dc", "O5uR6d LTKOO",
    "vL7GXd", "webanswers-webanswers_table_webanswers-table",
    "dOoNo ikB4Bb gsrt", "sXLa0e", "LWkFke", "VQF4g", "qv3Wpe", "kno-rdesc", "SPZ6b"
]

useragent = 'Mozilla/5.0(Windows NT 10.0;Win64)AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.75 Safari/537.36'

# Groq AI Client
client = Groq(api_key=GroqAPIKey)

# Professional responses
proffessional_responses = [
    "Your satisfaction is my top priority; feel free to reach out if there's anything else I can help you with.",
    "I'm here to help, and I'm always here to provide guidance and support.",
]

# System messages for the chatbot
messages = []
SystemChatBot = [{
    "role": "system",
    "content": "Hello, I am AI Assistant. You are a content writer. You have to write content like letters, codes, applications, essays, notes, songs, poems, poetry, etc."
}]


### Function Definitions ###

def GoogleSearch(Topic):
    """Searches the topic on Google."""
    search(Topic)
    return True


def Content(Topic):
    """Generates content using AI and opens it in Notepad."""
    
    def OpenNotepad(File):
        default_text_editor = 'notepad.exe'
        subprocess.Popen([default_text_editor, File])

    def ContentWriterAI(prompt):
        messages.append({"role": "user", "content": prompt})

        completion = client.chat.completions.create(
            model="llama3-70b-8192",  # ✅ Model Updated
            messages=SystemChatBot + messages,
            max_tokens=2048,
            temperature=0.7,
            top_p=1,
            stream=True,
        )

        Answer = ""
        for chunk in completion:
            if hasattr(chunk, "choices") and chunk.choices and chunk.choices[0].delta.content:
                Answer += chunk.choices[0].delta.content

        Answer = Answer.replace("</s>", "")
        messages.append({"role": "assistant", "content": Answer})
        return Answer

    Topic = Topic.lower().replace("content", "").strip()
    ContentByAI = ContentWriterAI(Topic)
    
    os.makedirs("Data", exist_ok=True)
    file_path = rf"Data\{Topic.replace(' ', '_')}.txt"

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(ContentByAI)

    OpenNotepad(file_path)
    return True


def YoutubeSearch(Topic):
    """Searches the topic on YouTube."""
    Url4search = f"https://www.youtube.com/results?search_query={Topic}"
    webbrowser.open(Url4search)
    return True


def PlayYoutube(query):
    """Plays a video on YouTube."""
    playonyt(query)
    return True


def OpenApp(app):
    """Opens an application."""
    try:
        appopen(app, match_closest=True, output=True, throw_error=True)
    except:
        def extract_links(html):
            if html is None:
                return []
            soup = BeautifulSoup(html, 'html.parser')
            links = soup.find_all('a', {'jsname': 'UWckNb'})
            return [link.get('href') for link in links]

        def search_google(query):
            url = f"https://www.google.com/search?q={query}"
            headers = {"User-Agent": useragent}
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.text
            return None
        
        html = search_google(app)
        if html:
            links = extract_links(html)
            if links:
                webopen(links[0])
    return True


def CloseApp(app):
    """Closes an application."""
    try:
        close(app, match_closest=True, output=True, throw_error=True)
        return True
    except:
        return False


def System(command):
    """Handles system-related commands like volume control."""
    commands = {
        "mute": lambda: keyboard.press_and_release("volume mute"),
        "unmute": lambda: keyboard.press_and_release("volume up"),
        "volume up": lambda: keyboard.press_and_release("volume up"),
        "volume down": lambda: keyboard.press_and_release("volume down"),
    }
    if command in commands:
        commands[command]()
    return True


async def TranslateAndExecute(commands: list[str]):
    """Translates and executes multiple automation commands asynchronously."""
    funcs = []
    for command in commands:
        if command.startswith("open"):
            funcs.append(asyncio.to_thread(OpenApp, command.removeprefix("open ").strip()))

        elif command.startswith("close"):
            funcs.append(asyncio.to_thread(CloseApp, command.removeprefix("close ").strip()))

        elif command.startswith("play"):
            funcs.append(asyncio.to_thread(PlayYoutube, command.removeprefix("play ").strip()))

        elif command.startswith("content"):
            funcs.append(asyncio.to_thread(Content, command.removeprefix("content ").strip()))

        elif command.startswith("google search"):
            funcs.append(asyncio.to_thread(GoogleSearch, command.removeprefix("google search ").strip()))

        elif command.startswith("youtube search"):
            funcs.append(asyncio.to_thread(YoutubeSearch, command.removeprefix("youtube search ").strip()))

        elif command.startswith("system"):
            funcs.append(asyncio.to_thread(System, command.removeprefix("system ").strip()))

        else:
            print(f"No function found for {command}")


    results = await asyncio.gather(*funcs)
    for result in results:
        yield result


async def Automation(commands: list[str]):
    """Handles automation commands in sequence."""
    async for _ in TranslateAndExecute(commands):
        pass
    return True


# Main Execution
if __name__ == "__main__":
    asyncio.run(Automation(["content Write a script for youtube video of title 'Negetive effects of Social Media'"]))
