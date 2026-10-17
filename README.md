# ✨ AURA

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
  <img src="https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/LangGraph-agent-1C3C3C?style=flat-square&logo=langchain&logoColor=white" alt="LangGraph">
  <img src="https://img.shields.io/badge/LLM-Groq-FF4F00?style=flat-square&logo=groq&logoColor=white" alt="Groq">
  <img src="https://img.shields.io/badge/UI-PyQt5-41CD52?style=flat-square&logo=qt&logoColor=white" alt="PyQt5">
</p>

A desktop AI assistant: a clean chat window backed by a LangGraph tool-calling agent.
Ask questions, get live answers from the web, and let it act on your computer.

---

## ✨ What it can do

| | |
|---|---|
| 💬 **Chat** | Streaming answers with full Markdown, syntax-highlighted code (one-click copy), live tool-progress chips, and light/dark themes that follow your GNOME setting. |
| 🌐 **Live web search** | Current news, prices, scores, anything recent (DuckDuckGo, no key needed). |
| 📄 **Read pages & PDFs** | "Summarize this article: <url>" — fetches the page or PDF and reads it. |
| 🌦️ **Weather** | Current conditions and today's forecast for any city (no key needed). |
| 🖥️ **Apps & websites** | Open or close desktop apps, open websites. |
| 🎵 **YouTube** | "play believer" finds the track and opens it. |
| 🔊 **Volume** | Mute, unmute, up, down. |
| 📝 **Writing** | Emails, letters, essays, code: written, saved and opened in your editor. |
| 📋 **Clipboard** | "Translate what I copied", "copy that email to my clipboard". |
| 📁 **Files** | Find, list and read files and PDFs in your home folder ("summarize ~/Downloads/report.pdf"). Access outside your home folder is refused. |
| ⏰ **Reminders** | "Remind me in 20 minutes to stretch", "remind me tomorrow at 9:00 to call mum". Desktop notification when due; list and cancel them too. |
| ⌨️ **Global hotkey** | Super+J shows/hides AURA from anywhere (starts it if it isn't running). |
| 🟢 **Always on** | Starts hidden at login; closing the window keeps it running in the background (Ctrl+Q quits). |
| ⚡ **Never stalls** | When a model hits Groq's rate limit, AURA switches to another model instantly; if all are busy it shows a countdown. Stop any reply with Esc or the stop button. |
| 🖼️ **Images** | Text-to-image via Hugging Face (optional key). |
| 🧠 **Memory** | Remembers you across chats: facts (where you study, people you mention, preferences, upcoming events) and a short note per day. Learns in the background after you chat, or when you say "remember…" / "forget…". A Memory panel (✦ in the header) lets you see, edit and delete everything, or turn learning off. Stored only on your computer. |

You don't use commands; just say what you want. The agent decides which tools to use, and can chain several in one request ("open firefox and tell me today's top tech story").

---

## 🚀 Setup

```bash
git clone https://github.com/aliii-codes/Jarvis-AI-v2.git
cd Jarvis-AI-v2

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # or: uv sync

cat > .env <<'EOF'
GroqAPIKey=your_groq_api_key_here
Username=YourName
Assistantname=AURA
# Optional:
HuggingFaceAPIKey=
# ChatModel=openai/gpt-oss-120b
# FallbackModels=openai/gpt-oss-20b,qwen/qwen3.8-27b
# SummaryModel=openai/gpt-oss-20b
EOF

python main.py
```

Get a free Groq key at [console.groq.com](https://console.groq.com).

### 🟢 Start at login

```bash
python main.py --install-autostart     # start hidden at login + add AURA to the app menu
python main.py --uninstall-autostart
```

### ⌨️ Global hotkey

```bash
python main.py --install-hotkey            # GNOME: Super+J toggles AURA
python main.py --install-hotkey "<Ctrl><Alt>j"   # pick another key
python main.py --uninstall-hotkey
```

Wayland doesn't let apps grab keys directly, so this adds a GNOME custom shortcut that runs
`main.py --toggle`. On other desktops, bind that command to a key in your keyboard settings.
AURA runs as a single instance: launching it again just brings the window back.

Reminders fire only while AURA is running. Hide it with the hotkey instead of closing it, and they'll still pop up.

### 🐧 Linux

```bash
sudo apt install pulseaudio-utils xdg-utils libnotify-bin
```

`pactl` (from `pulseaudio-utils`, works with PipeWire too) handles volume; `xdg-open` opens saved documents and images; `notify-send` (from `libnotify-bin`) shows reminder notifications.
"Open <app>" launches the matching executable on your `PATH`; "close <app>" uses `pkill`.

> **Free tier note:** Groq's free tier allows 8,000 tokens per minute, and it counts each reply's
> `max_tokens` allowance against that. AURA keeps requests small (old tool results are cleared,
> history is summarized, replies capped at `MaxTokens=1024`), and if you send several tool-heavy
> messages within a minute it waits and retries automatically. On a paid tier, raise `MaxTokens` in `.env`.

---

## 🏗️ How it works

```
main.py
aura/
├── config.py   # settings from .env
├── tools.py      # 20 LangChain tools: web_search, read_url, read_file, set_reminder, ...
├── agent.py      # LangGraph agent (create_agent) + SQLite memory + middleware
├── reminders.py  # reminder storage (SQLite)
├── hotkey.py     # GNOME shortcut installer
├── desktop.py    # autostart + app menu entries
├── memory.py     # long-term memory (LangGraph SqliteStore): facts + daily notes
├── learner.py    # background memory agent that extracts facts from conversations
├── ui.py         # Qt window hosting the web UI; agent on a worker thread; single-instance + reminders
└── web/          # the chat UI: index.html, app.css, app.js + vendored marked, DOMPurify, highlight.js, Inter
Data/             # memory, reminders, saved documents and images (git-ignored)
```

- **Agent**: `langchain.agents.create_agent` builds a LangGraph ReAct loop around `ChatGroq`. The model reads each tool's docstring and decides what to call.
- **Middleware**: a dynamic system prompt (injects the current date/time), `SummarizationMiddleware` (compresses old history past ~4k tokens), `ContextEditingMiddleware` (sends old tool results as `[cleared]`), `ToolErrorMiddleware` (failed tools are reported to the model instead of crashing), and `ModelCallLimitMiddleware` (caps runaway tool loops).
- **Conversation memory**: `SqliteSaver` checkpointer in `Data/memory.sqlite`. "New chat" starts a new thread; old ones stay saved.
- **Long-term memory**: a LangGraph `SqliteStore` (`Data/memory_store.sqlite`) holds facts and daily notes, injected into the system prompt each turn (older days via the `recall` tool). After ~45s of quiet, a background agent on the small model reads new messages and returns structured add / update / delete operations; it skips one-off requests, secrets and sensitive topics, and converts relative dates to absolute ones.
- **Rate limits**: a custom middleware tries `ChatModel`, then each of `FallbackModels` (every Groq model has its own tokens-per-minute budget), and only waits when all are limited, streaming the countdown to the UI. Stop is cancellable at any point, and the saved history is repaired so a cancelled tool call never breaks the next request.
- **Streaming**: `graph.stream(..., stream_mode=["messages", "updates"])` yields tokens and tool calls, which the Qt side forwards to the page over `QWebChannel`.
- **UI**: a local web page rendered by QtWebEngine. Model output is rendered with `marked` and sanitized with `DOMPurify`; all assets are bundled, nothing loads from the internet. Links open in your browser.

Adding a tool is one decorated function in `aura/tools.py` plus an entry in `TOOLS`.

---

## 🤝 Contributing

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/your-feature-name`.
3. Commit changes: `git commit -m "Add your feature"`.
4. Push to the branch: `git push origin feature/your-feature-name`.
5. Open a pull request.

## 🐞 Bug Reports & Feature Requests

Submit issues [here](https://github.com/aliii-codes/Jarvis-AI-v2/issues).

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🎉 Acknowledgements

- **Groq** for fast inference.
- **LangChain / LangGraph** for the agent framework.
- **Open-source libraries**: `ddgs`, `PyQt5`, `beautifulsoup4`, `pypdf`, `AppOpener`, `python-dotenv`, `requests`.
