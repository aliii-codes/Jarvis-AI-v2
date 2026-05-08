# 🤖 Jarvis AI v2


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
  <img src="https://img.shields.io/badge/Auth-JWT-black?style=flat-square&logo=jsonwebtokens&logoColor=white" alt="Auth">
  <img src="https://img.shields.io/badge/Async-True-purple?style=flat-square&logo=python&logoColor=white" alt="Async">
</p>

---

## 🔥 What's New in v2?

This isn't just an update. It's a **complete rewrite** from the ground up.

- **⚡ Groq Whisper Integration** — Blazing-fast, ultra-accurate speech transcription.
- **🛡️ Dual Speech Recognition** — Fallback to Web Speech API if Groq hiccups. Zero downtime.
- **🧹 Selenium Purged** — Lighter, faster, no more ChromeDriver headaches.
- **🔒 Secure Authentication** — User profiles, settings, and history protected.
- **⚙️ True Multitasking** — Processes run in the **background** while you keep chatting.
- **🎨 Modern UI** — Clean, responsive interface built with CustomTkinter.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Commands** | Seamless voice interaction with Groq Whisper + Web Speech API fallback. |
| 💬 **Text Chat** | Type commands for quiet, discrete interaction. |
| 🌐 **Real-Time Web Search** | Fetch live information, news, and answers instantly. |
| 🖼️ **AI Image Generation** | Create images from text prompts in the background. |
| 🤖 **Automation** | Open apps, control system volume, play music, and more. |
| 🔊 **Text-to-Speech** | Natural, high-quality voice responses. |
| 🔐 **User Authentication** | Secure login system with profile management. |
| ⚡ **Async Operations** | Long-running tasks never freeze the UI. |

---

## 💻 Tech Stack

| Category | Technologies |
|----------|--------------|
| **Core Language** | Python 3.9+ |
| **Speech-to-Text** | Groq Whisper + Web Speech API |
| **LLM** | Groq API (Llama 3, Mixtral) |
| **Text-to-Speech** | pyttsx3 |
| **GUI** | Tkinter (CustomTkinter) |
| **Authentication** | Custom Auth Module (hashlib, secrets) |
| **Automation** | AppOpener, PyWhatKit, Keyboard |
| **Concurrency** | asyncio, threading, subprocess |

---

## 🚀 Installation

```bash
# 1. Clone the repository
git clone https://github.com/aliii-codes/Jarvis-AI-v2.git
cd Jarvis-AI-v2

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate       # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables (create .env file)
echo "GROQ_API_KEY=your_groq_api_key_here" > .env
# Optional keys:
# echo "REPLICATE_API_TOKEN=your_replicate_token_here" >> .env
# echo "NEWS_API_KEY=your_news_api_key_here" >> .env

# 5. Run Jarvis AI
python main.py
```

## 🕹️ Usage


```
| Command               | Description                                  |
|-----------------------|----------------------------------------------|
| `content <topic>`     | Generate content and open in Notepad.        |
| `google search <query>` | Search Google for the query.                 |
| `play <video>`        | Play a YouTube video.                        |
| `open <app>`          | Open an application or website.              |
| `system <command>`    | Control system settings (e.g., volume).      |

## 📁 Project Structure

```
Jarvis-AI-v2/
├── Backend/
│   ├── Auth.py               # User authentication & session management
│   ├── Automation.py         # System/app control (open, volume, play music)
│   ├── ChatBot.py            # Groq LLM interaction logic
│   ├── ImageGeneration.py    # AI image generation via Replicate
│   ├── Model.py              # Intent classification & first-layer routing
│   ├── RealtimeSearchEngine.py # Live web scraping & news fetching
│   ├── SpeechToText.py       # Groq Whisper + Web Speech API fallback
│   ├── TextToSpeech.py       # Voice synthesis engine
│   └── Weather.py            # Real-time weather data fetcher
│
├── Frontend/
│   ├── GUI.py                # Main PyQt5 application window
│   ├── StarfieldWidget.py    # Animated background canvas
│   ├── StarfieldDesign.md    # Design notes for the starfield effect
│   ├── Files/                # Persistent local data storage
│   │   ├── Database.data
│   │   ├── Imagegeneration.data
│   │   ├── Mic.data
│   │   ├── Responses.data
│   │   └── Status.data
│   └── Graphics/             # UI assets & icons
│       ├── Home.png
│       ├── Jarvis.gif
│       ├── Maximize.png
│       ├── Mic_off.png
│       ├── Mic_on.png
│       ├── Minimize.png
│       ├── Minimize2.png
│       └── Settings.png
│
├── Temp/                     # Temporary session cache
│   ├── Database.data
│   └── Responses.data
│
├── .gitignore                # Git ignored files & folders
├── main.py                   # Application entry point
├── password.txt              # (Ensure this is in .gitignore if real)
├── pyproject.toml            # Project metadata & build config
├── requirements.txt          # Python package dependencies
└── README.md                 # You are here
```

## 🤝 Contributing

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/your-feature-name`.
3. Commit changes: `git commit -m "Add your feature"`.
4. Push to the branch: `git push origin feature/your-feature-name`.
5. Open a pull request.

## 🐞 Bug Reports & Feature Requests

Submit issues [here](https://github.com/aliii-codes/Jarvis-AI-v2/issues) using the provided templates.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🎉 Acknowledgements

- **Groq**: For providing powerful AI models.
- **Open-Source Libraries**: `AppOpener`, `PyWhatKit`, `python-dotenv`, `requests`, `beautifulsoup4`, 'groq', 'pil'.
```
