<p align="center">
  <img src="https://raw.githubusercontent.com/aliii-codes/Jarvis-AI-v2/main/Frontend/Graphics/Jarvis.gif" alt="Jarvis AI Logo" width="200"/>
</p>

<h1 align="center">🤖 Jarvis AI v2</h1>

<p align="center">
  <b>The Evolution.</b> Faster. Smarter. Unchained.
</p>

<p align="center">
  <a href="https://github.com/aliii-codes/Jarvis-AI-v2/stargazers"><img src="https://img.shields.io/github/stars/aliii-codes/Jarvis-AI-v2?style=for-the-badge&logo=github&color=gold" alt="Stars"></a>
  <a href="https://github.com/aliii-codes/Jarvis-AI-v2/network/members"><img src="https://img.shields.io/github/forks/aliii-codes/Jarvis-AI-v2?style=for-the-badge&logo=github&color=blue" alt="Forks"></a>
  <a href="https://github.com/aliii-codes/Jarvis-AI-v2/issues"><img src="https://img.shields.io/github/issues/aliii-codes/Jarvis-AI-v2?style=for-the-badge&logo=github" alt="Issues"></a>
  <a href="https://github.com/aliii-codes/Jarvis-AI-v2/blob/main/LICENSE"><img src="https://img.shields.io/github/license/aliii-codes/Jarvis-AI-v2?style=for-the-badge&logo=opensourceinitiative" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Groq-Whisper-FF4F00?style=flat-square&logo=groq&logoColor=white" alt="Groq Whisper">
  <img src="https://img.shields.io/badge/UI-Tkinter-FF6F00?style=flat-square&logo=python&logoColor=white" alt="Tkinter">
  <img src="https://img.shields.io/badge/Auth-JWT-black?style=flat-square&logo=jsonwebtokens&logoColor=white" alt="JWT">
  <img src="https://img.shields.io/badge/Async-True-purple?style=flat-square&logo=python&logoColor=white" alt="Async">
</p>

---

## 🔥 What's New in v2?

This isn't just an update. It's a **complete rewrite** from the ground up. Jarvis AI v2 is built for speed, reliability, and a modern user experience.

*   **⚡ Groq Whisper Integration**: Blazing-fast, ultra-accurate speech transcription powered by Groq's LPU inference. It's not just fast, it's **real-time**.
*   **🛡️ Dual Speech Recognition**: Robust fallback to native browser Web Speech API. If Groq hiccups, Jarvis keeps listening. No downtime.
*   **🧹 Selenium Purged**: We removed the slow, clunky Selenium dependency. The entire core is lighter, faster, and more reliable.
*   **🔒 Secure Authentication**: User profiles, settings, and history are now protected with a robust auth system. Your data is yours.
*   **⚙️ True Multitasking**: Processes run in the **background**. Ask Jarvis to scrape a website, generate an image, or analyze a file while you keep the conversation going. No blocking.
*   **🎨 Modern UI**: A complete visual overhaul. Clean, responsive, and intuitive.

## ✨ Features

<table>
  <tr>
    <td>🎤 Voice Commands</td>
    <td>Seamless voice interaction with <code>Groq Whisper</code> and fallback to Web Speech API.</td>
  </tr>
  <tr>
    <td>💬 Text Chat</td>
    <td>Type commands for a quiet, discrete interaction.</td>
  </tr>
  <tr>
    <td>🌐 Real-Time Web Search</td>
    <td>Fetch live information, news, and answers instantly.</td>
  </tr>
  <tr>
    <td>🖼️ AI Image Generation</td>
    <td>Create images from text prompts in the background.</td>
  </tr>
  <tr>
    <td>🤖 Automation</td>
    <td>Open apps, control system volume, play music, and more.</td>
  </tr>
  <tr>
    <td>🔊 Text-to-Speech</td>
    <td>Natural, high-quality voice responses (customizable voice).</td>
  </tr>
  <tr>
    <td>🔐 User Authentication</td>
    <td>Secure login system with profile management.</td>
  </tr>
  <tr>
    <td>⚡ Async Operations</td>
    <td>Long-running tasks never freeze the UI.</td>
  </tr>
</table>

## 📸 Preview

<p align="center">
  <img src="https://raw.githubusercontent.com/aliii-codes/Jarvis-AI-v2/main/Frontend/Graphics/Home.png" alt="Jarvis AI v2 Interface" width="800"/>
</p>

## 🛠️ Tech Stack

| Category | Technology |
|----------|------------|
| **Core Language** | ![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white) |
| **Speech-to-Text** | ![Groq](https://img.shields.io/badge/Groq_Whisper-FF4F00?style=flat&logo=groq&logoColor=white) + ![Web Speech API](https://img.shields.io/badge/Web_Speech_API-4285F4?style=flat&logo=google&logoColor=white) |
| **LLM** | Groq API (Llama 3, Mixtral) |
| **Text-to-Speech** | pyttsx3 / gTTS |
| **GUI** | Tkinter (CustomTkinter) |
| **Authentication** | Custom Auth Module |
| **Concurrency** | `asyncio`, `threading`, `subprocess` |
| **Image Generation** | Replicate API / Stability AI |

## 🚀 Installation

Get Jarvis up and running in under 2 minutes.

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/aliii-codes/Jarvis-AI-v2.git
cd Jarvis-AI-v2

### 2️⃣  Set Up Virtual Environment (Recommended)
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

### 3️⃣ Install Dependencies
pip install -r requirements.txt

### 4️⃣ Configure API Keys
Create a .env file in the root directory and add your keys:
GROQ_API_KEY=your_groq_api_key_here
REPLICATE_API_TOKEN=your_replicate_token_here
NEWS_API_KEY=your_news_api_key_here

💡 Get Your Free API Keys:

Groq: Sign up at console.groq.com for a generous free tier.

Replicate: Get a token at replicate.com/account/api-tokens.

News API: Register at newsapi.org.


### 5️⃣ Launch Jarvis

python main.py

```

# 📖 Usage Guide

Voice Commands
Click the Microphone icon.

Speak your command clearly.

Jarvis will transcribe using Groq Whisper (or fallback to Web Speech API) and execute.

Example Commands
Category	Command Examples
General	"What is the capital of France?"
Real-Time Search	"Who won the NBA finals last night?"
Automation	"Open Chrome", "Play music", "Increase volume"
Image Generation	"Generate an image of a futuristic city at sunset"
System	"Shutdown in 10 minutes", "Lock my PC"
📁 Project Structure
text
Jarvis-AI-v2/
├── Backend/
│   ├── Auth.py               # User authentication & profiles
│   ├── Automation.py         # System & app automation
│   ├── ChatBot.py            # LLM interaction (Groq)
│   ├── ImageGeneration.py    # AI image generation
│   ├── Model.py              # First-layer decision model
│   ├── RealtimeSearchEngine.py # Live web search
│   ├── SpeechToText.py       # Groq Whisper + Web Speech API
│   ├── TextToSpeech.py       # Voice synthesis
│   └── Weather.py            # Weather information
├── Frontend/
│   ├── GUI.py                # Main graphical interface
│   ├── StarfieldWidget.py    # Animated background
│   ├── Files/                # Data & cache files
│   └── Graphics/             # Icons, logos, GIFs
├── Temp/                     # Temporary session files
├── main.py                   # Application entry point
├── requirements.txt          # Python dependencies
├── .env                      # API keys (ignored by git)
└── README.md                 # You are here!
🤝 Contributing
We love contributions! Here's how you can help:

Fork the repository.

Create a new branch: git checkout -b feature/your-amazing-feature

Make your changes and commit: git commit -m "Add amazing feature"

Push to your branch: git push origin feature/your-amazing-feature

Open a Pull Request.

🐛 Bug Reports & Feature Requests
Found a bug? Have a killer idea? Open an issue on GitHub:

Report a Bug

Request a Feature

📜 License
This project is open-source and available under the MIT License.

⭐ Acknowledgements
Jarvis AI v2 stands on the shoulders of giants:

Groq - For their insanely fast LPU inference and Whisper API.

SpeechRecognition - The backbone of our dual STT system.

CustomTkinter - For the sleek, modern UI components.

The Open Source Community - For endless inspiration and tools.

<p align="center"> Made with ❤️ by <a href="https://github.com/aliii-codes">aliii-codes</a> </p> ```
