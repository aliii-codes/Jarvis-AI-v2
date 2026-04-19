from googlesearch import search
from groq import Groq
from json import load, dump
import datetime
from dotenv import dotenv_values

# Load environment variables
env_vars = dotenv_values(".env")

Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
GroqAPIKey = env_vars.get("GroqAPIKey")

client = Groq(api_key=GroqAPIKey)

System = f"""
Hello, I am {Username}, and you are {Assistantname}, a highly accurate and advanced AI chatbot with real-time internet access.
*** Answer questions professionally, using proper grammar, punctuation, and clarity. ***
*** Provide answers only based on the available data. ***
"""

try:
    with open(r"Data/ChatLog.json", "r") as f:
        messages = load(f)
except:
    messages = []
    with open(r"Data/ChatLog.json", "w") as f:
        dump(messages, f)

def GoogleSearch(query):
    results = list(search(query, advanced=True, num_results=5))
    if not results:
        return "No results found for this query."
    
    answer = f"The search results for '{query}' are:\n[start]\n"
    for res in results:
        answer += f"Title: {res.title}\nDescription: {res.description}\n\n"
    
    return answer + "[end]"

def AnswerModifier(answer):
    return '\n'.join(line for line in answer.split('\n') if line.strip())

SystemChatBot = [
    {"role": "system", "content": System},
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello! How can I help you?"}
]

def Information():
    now = datetime.datetime.now()
    return f"""
Use this real-time information if needed:
Day: {now.strftime('%A')}
Date: {now.strftime('%d')}
Month: {now.strftime('%B')}
Year: {now.strftime('%Y')}
Time: {now.strftime('%H')} hours, {now.strftime('%M')} minutes, {now.strftime('%S')} seconds.
"""

def RealtimeSearchEngine(prompt):
    global SystemChatBot, messages
    
    messages.append({"role": "user", "content": prompt})
    SystemChatBot.append({"role": "user", "content": GoogleSearch(prompt)})
    
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=SystemChatBot + [{"role": "user", "content": Information()}] + messages,
        temperature=0.7,
        max_tokens=2048,
        top_p=1,
        stream=True,
        stop=None
    )
    
    answer = ""
    for chunk in completion:
        if chunk.choices[0].delta.content:
            answer += chunk.choices[0].delta.content
    
    answer = answer.strip().replace("</s>", "")
    messages.append({"role": "assistant", "content": answer})
    
    with open(r"Data/ChatLog.json", "w") as f:
        dump(messages, f, indent=4)
    
    SystemChatBot.pop()
    return AnswerModifier(answer)

if __name__ == "__main__":
    while True:
        prompt = input("Enter Your Query: ")
        print(RealtimeSearchEngine(prompt))


        