# Jarvis-AI-v2

## Overview
Jarvis-AI-v2 is an advanced AI assistant designed to handle a variety of tasks, including user authentication, automation, and conversational AI. The project is built with a focus on security, modularity, and real-time functionality.

## Features
- **User Authentication**: Secure user profile management with password hashing and salting.
- **Automation**: Execute system commands, open/close applications, search the web, and generate content.
- **Conversational AI**: Real-time chatbot with internet knowledge and professional responses.
- **Profile Management**: Create, update, and delete user profiles with customizable settings.
- **Chat History**: Persistent chat logs for seamless conversation continuity.

## Tech Stack
- **Python**: Core programming language.
- **Groq API**: For AI model inference.
- **AppOpener**: For application control.
- **pywhatkit**: For web searches and YouTube interactions.
- **BeautifulSoup**: For web scraping.
- **dotenv**: For environment variable management.
- **hashlib**: For secure password hashing.

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/aliii-codes/Jarvis-AI-v2.git
   cd Jarvis-AI-v2
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in a `.env` file:
   ```env
   GroqAPIKey=your_groq_api_key
   Username=your_username
   Assistantname=your_assistant_name
   ```

## Usage Examples
### Authentication
```python
from Backend.Auth import create_profile, verify_login

# Create a new profile
create_profile("john_doe", "securepassword", "Jarvis", "en-US-JennyNeural")

# Verify login
profile = verify_login("john_doe", "securepassword")
print(profile)
```

### Automation
```python
import asyncio
from Backend.Automation import Automation

# Run automation commands
asyncio.run(Automation([
    "open chrome",
    "google search latest AI trends",
    "content Write a script for a YouTube video titled 'Negative effects of Social Media'"
]))
```

### Chatbot
```python
from Backend.ChatBot import ChatBot

# Interact with the chatbot
response = ChatBot("What are the latest advancements in AI?")
print(response)
```

## Project Structure
```
Jarvis-AI-v2/
│
├── Backend/
│   ├── Auth.py
│   ├── Automation.py
│   └── ChatBot.py
│
├── Data/
│   └── profiles.json
│
├── .env
└── README.md
```

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

**Note:** Ensure you have the necessary API keys and dependencies installed before running the project. The `.env` file should be kept secure and not shared publicly.
