from groq import Groq
from dotenv import dotenv_values
import logging

env_vars = dotenv_values(".env")
GroqAPIKey = env_vars.get("GroqAPIKey")

client = Groq(api_key=GroqAPIKey)

FUNCTIONS = [
    "exit", "general", "realtime", "open", "close", "play",
    "generate image", "system", "content", "google search", "youtube search", "reminder"
]

SYSTEM_PROMPT = """You are a command routing model for an AI assistant. Classify user input into one or more actions. Respond ONLY with the action label(s) — no explanations, no markdown.

Available actions:
- general (query)        → Conversational/factual questions an LLM can answer without real-time data
- realtime (query)       → Questions needing current/live internet data
- open (name)            → Open an app or website
- close (name)           → Close an app or website
- play (song name)       → Play music on YouTube
- generate image (desc)  → Generate an AI image
- system (task)          → System commands: mute, unmute, volume up, volume down, screenshot
- content (topic)        → Write content: code, essays, emails, letters, etc.
- google search (query)  → Search Google
- youtube search (query) → Search YouTube
- reminder (datetime message) → Set a reminder
- exit                   → User wants to quit

Rules:
- Separate multiple actions with ", "
- Default to "general (query)" if unsure
- Respond with ONLY the action label(s), nothing else

Examples:
User: "open chrome and tell me about python"  → open chrome, general tell me about python
User: "what is today's news?"                 → realtime what is today's news?
User: "how are you?"                          → general how are you?
User: "play despacito"                        → play despacito
User: "mute my laptop"                        → system mute
User: "bye"                                   → exit
"""

def FirstLayerDMW(prompt: str) -> list[str]:
    """Route user query to appropriate handler(s). Returns a list of action strings."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            max_tokens=128,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        tasks = [t.strip() for t in raw.split(",") if t.strip()]

        valid = []
        for task in tasks:
            for func in FUNCTIONS:
                if task.lower().startswith(func):
                    valid.append(task)
                    break
            else:
                valid.append(f"general {task}")

        return valid if valid else [f"general {prompt}"]

    except Exception as e:
        logging.error(f"Routing error: {e}")
        return [f"general {prompt}"]


if __name__ == "__main__":
    while True:
        print(FirstLayerDMW(input(">>> ")))