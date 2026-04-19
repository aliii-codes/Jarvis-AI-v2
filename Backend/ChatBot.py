from groq import Groq
from json import load, dump, loads
import datetime
from dotenv import dotenv_values


env_vars = dotenv_values(".env")

# API Credentials
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
GroqAPIKey = env_vars.get("GroqAPIKey")


client = Groq(api_key=GroqAPIKey)


SystemMessage = f"""Hello, I am {Username}, and you are {Assistantname}, a professional AI assistant with real-time internet knowledge. 
Answer concisely and professionally with proper grammar.
"""


CHAT_LOG_PATH = r"Data\ChatLog.json"


def load_chat_history():
    try:
        with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
        return loads(content) if content else []
    except (FileNotFoundError, ValueError):
        with open(CHAT_LOG_PATH, "w", encoding="utf-8") as f:
            dump([], f)
        return []


messages = load_chat_history()





def RealtimeInformation():
    now = datetime.datetime.now()
    return (
        f"Current Date and Time:\n"
        f"Day: {now.strftime('%A')}\n"
        f"Date: {now.strftime('%d %B %Y')}\n"
        f"Time: {now.strftime('%H:%M:%S')}\n"
    )


def AnswerModifier(Answer):
    return '\n'.join([line.strip() for line in Answer.split('\n') if line.strip()])

def ChatBot(query):
    global messages

    try:
        messages.append({"role": "user", "content": query})

        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": SystemMessage}] +
                     [{"role": "system", "content": RealtimeInformation()}] +
                     messages,
            max_tokens=1024,
            temperature=0.7,
            top_p=1,
            stream=False, 
        )

      
        Answer = response.choices[0].message.content.strip() if response.choices else "No response received."
        

    
        Answer = Answer.replace("</s>", "")

     
        messages.append({"role": "assistant", "content": Answer})

        # Save chat history
        with open(CHAT_LOG_PATH, "w") as f:

            dump(messages, f, indent=4)

        return AnswerModifier(Answer)

    except Exception as e:
        print(f"Error: {e}")
        return "An error occurred while processing your request."


if __name__ == "__main__":
    while True:
        user_input = input("Enter Your Question: ")
        print(ChatBot(user_input))