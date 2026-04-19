import sys
import os
import json
import logging

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QFrame, QStackedWidget,
    QDialog, QFormLayout, QComboBox, QMessageBox, QScrollArea,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QObject
from PyQt5.QtGui import QMovie, QColor, QFont, QTextCharFormat, QTextBlockFormat
from dotenv import dotenv_values, set_key

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from Backend.Auth import (
    load_profiles, verify_login, create_profile,
    update_settings, update_display_name, change_password,
)

def resource_path(rel: str) -> str:
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.abspath(".")
    return os.path.join(base, rel)

GRAPHICS_DIR = resource_path(os.path.join("Frontend", "Graphics"))
TEMP_DIR     = resource_path(os.path.join("Frontend", "Files"))
DATA_DIR     = resource_path("Data")
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

def gfx(fn): return os.path.join(GRAPHICS_DIR, fn)

BG=      "#0a0a12"; SURFACE= "#12121f"; SIDEBAR= "#0d0d1a"
ACCENT=  "#00c8ff"; PURPLE=  "#7b5cfa"; TEXT=    "#e0e0f0"
MUTED=   "#6a6a8a"; BORDER=  "#1e1e3a"; SUCCESS= "#00e5a0"; DANGER= "#ff4d6d"

GLOBAL_STYLE = f"""
QMainWindow,QDialog{{background-color:{BG};}}
QWidget{{background-color:{BG};color:{TEXT};font-family:'Segoe UI',Arial,sans-serif;}}
QPushButton{{background-color:{SURFACE};color:{TEXT};border:1px solid {BORDER};border-radius:8px;padding:8px 16px;font-size:13px;}}
QPushButton:hover{{background-color:#1e1e35;border-color:{ACCENT};color:{ACCENT};}}
QPushButton:pressed{{background-color:#08080f;}}
QLineEdit{{background-color:{SURFACE};color:{TEXT};border:1px solid {BORDER};border-radius:6px;padding:9px 12px;font-size:13px;}}
QLineEdit:focus{{border-color:{ACCENT};}}
QTextEdit{{background-color:#0d0d1a;color:{TEXT};border:none;font-size:14px;}}
QScrollBar:vertical{{background:{BG};width:6px;border-radius:3px;}}
QScrollBar::handle:vertical{{background:{BORDER};border-radius:3px;}}
QScrollBar::handle:vertical:hover{{background:{ACCENT};}}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}
QComboBox{{background-color:{SURFACE};color:{TEXT};border:1px solid {BORDER};border-radius:6px;padding:6px 10px;}}
QComboBox:focus{{border-color:{ACCENT};}}
QComboBox QAbstractItemView{{background-color:{SURFACE};color:{TEXT};selection-background-color:#1e1e35;border:1px solid {BORDER};}}
QLabel{{background-color:transparent;color:{TEXT};}}
QFrame{{background-color:transparent;}}
"""

VOICES = [
    ("Jenny (US · Female)",   "en-US-JennyNeural"),
    ("Guy (US · Male)",       "en-US-GuyNeural"),
    ("Aria (US · Female)",    "en-US-AriaNeural"),
    ("Ryan (UK · Male)",      "en-GB-RyanNeural"),
    ("Sonia (UK · Female)",   "en-GB-SoniaNeural"),
    ("Natasha (AU · Female)", "en-AU-NatashaNeural"),
    ("William (AU · Male)",   "en-AU-WilliamNeural"),
]

class AppSignals(QObject):
    status_update = pyqtSignal(str)
    chat_message  = pyqtSignal(str)
    mic_toggled   = pyqtSignal(bool)

signals = AppSignals()

_mic_active       = False
_assistant_status = "Available..."
_current_profile: dict | None = None

def SetMicrophoneStatus(val):
    global _mic_active
    _mic_active = val.lower() == "true" if isinstance(val, str) else bool(val)
    signals.mic_toggled.emit(_mic_active)

def GetMicrophoneStatus() -> str:
    return "True" if _mic_active else "False"

def SetAssistantStatus(status: str):
    global _assistant_status
    _assistant_status = status
    signals.status_update.emit(status)

def GetAssistantStatus() -> str:
    return _assistant_status

def ShowTextToScreen(text: str):
    signals.chat_message.emit(text)

def GetCurrentProfile():
    return _current_profile

def AnswerModifier(text: str) -> str:
    return '\n'.join(l for l in text.split('\n') if l.strip())

def QueryModifier(query: str) -> str:
    q = query.lower().strip()
    words = q.split()
    if words and words[0] in {"how","what","who","where","when","why","which","whose","whom"}:
        q = q.rstrip('.?!') + "?"
    else:
        q = q.rstrip('.?!') + "."
    return q.capitalize()

def TempDirPath(filename: str) -> str:
    return os.path.join(TEMP_DIR, filename)

# ─── Auth: Profile Card ───────────────────────────────────────────────────────
class ProfileCard(QFrame):
    clicked = pyqtSignal(str)
    def __init__(self, display_name: str, key: str):
        super().__init__()
        self.key = key
        self.setFixedSize(140, 160)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"QFrame{{background-color:{SURFACE};border:1px solid {BORDER};border-radius:12px;}}QFrame:hover{{border-color:{ACCENT};background-color:#1a1a2e;}}")
        lay = QVBoxLayout(self); lay.setAlignment(Qt.AlignCenter); lay.setSpacing(10)
        av = QLabel(display_name[0].upper()); av.setAlignment(Qt.AlignCenter); av.setFixedSize(64, 64)
        av.setStyleSheet(f"background-color:{PURPLE};color:white;border-radius:32px;font-size:26px;font-weight:bold;")
        lay.addWidget(av, alignment=Qt.AlignCenter)
        nm = QLabel(display_name); nm.setAlignment(Qt.AlignCenter)
        nm.setStyleSheet(f"color:{TEXT};font-size:13px;font-weight:600;"); lay.addWidget(nm)
    def mousePressEvent(self, _): self.clicked.emit(self.key)

class PasswordDialog(QDialog):
    def __init__(self, display_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Login"); self.setFixedWidth(340); self.setStyleSheet(GLOBAL_STYLE)
        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(24,24,24,24)
        lay.addWidget(QLabel(f"Welcome, {display_name}", styleSheet=f"font-size:16px;font-weight:700;color:{ACCENT};"))
        self.pwd = QLineEdit(); self.pwd.setPlaceholderText("Enter password")
        self.pwd.setEchoMode(QLineEdit.Password); self.pwd.returnPressed.connect(self.accept)
        lay.addWidget(self.pwd)
        self.err = QLabel(""); self.err.setStyleSheet(f"color:{DANGER};font-size:12px;"); lay.addWidget(self.err)
        btn = QPushButton("Login  →")
        btn.setStyleSheet(f"background-color:{ACCENT};color:#000;font-weight:700;border:none;padding:10px;border-radius:8px;")
        btn.clicked.connect(self.accept); lay.addWidget(btn)
    @property
    def password(self): return self.pwd.text()
    def show_error(self, msg): self.err.setText(msg)

class CreateProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Profile"); self.setFixedWidth(380); self.setStyleSheet(GLOBAL_STYLE)
        lay = QVBoxLayout(self); lay.setSpacing(14); lay.setContentsMargins(24,24,24,24)
        lay.addWidget(QLabel("Create New Profile", styleSheet=f"font-size:17px;font-weight:700;color:{ACCENT};"))
        form = QFormLayout(); form.setSpacing(10)
        self.u = QLineEdit(); self.u.setPlaceholderText("Your name (e.g. Ali)"); form.addRow("Username", self.u)
        self.a = QLineEdit("Jarvis"); self.a.setPlaceholderText("e.g. Jarvis"); form.addRow("Assistant Name", self.a)
        self.v = QComboBox()
        for label, _ in VOICES: self.v.addItem(label)
        form.addRow("Voice", self.v)
        self.p = QLineEdit(); self.p.setPlaceholderText("Password"); self.p.setEchoMode(QLineEdit.Password); form.addRow("Password", self.p)
        self.p2 = QLineEdit(); self.p2.setPlaceholderText("Confirm password"); self.p2.setEchoMode(QLineEdit.Password); form.addRow("Confirm", self.p2)
        lay.addLayout(form)
        self.err = QLabel(""); self.err.setStyleSheet(f"color:{DANGER};font-size:12px;"); lay.addWidget(self.err)
        btn = QPushButton("Create Profile")
        btn.setStyleSheet(f"background-color:{PURPLE};color:white;font-weight:700;border:none;padding:10px;border-radius:8px;")
        btn.clicked.connect(self._validate); lay.addWidget(btn)
    def _validate(self):
        u,p,p2 = self.u.text().strip(),self.p.text(),self.p2.text()
        if not u: self.err.setText("Username cannot be empty."); return
        if len(p)<4: self.err.setText("Password must be ≥ 4 characters."); return
        if p!=p2: self.err.setText("Passwords do not match."); return
        self.accept()
    @property
    def data(self):
        return {"username":self.u.text().strip(),"password":self.p.text(),
                "assistant_name":self.a.text().strip() or "Jarvis","voice":VOICES[self.v.currentIndex()][1]}

# ─── Auth Window ──────────────────────────────────────────────────────────────
class AuthWindow(QMainWindow):
    login_success = pyqtSignal(dict, str)
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis AI — Login"); self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet(GLOBAL_STYLE); self.setMinimumSize(700,520); self._drag=None
        central=QWidget(); self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        bar=QWidget(); bar.setFixedHeight(44); bar.setStyleSheet(f"background-color:{SIDEBAR};")
        bl=QHBoxLayout(bar); bl.setContentsMargins(16,0,8,0)
        bl.addWidget(QLabel("JARVIS AI",styleSheet=f"color:{ACCENT};font-size:14px;font-weight:800;letter-spacing:3px;"))
        bl.addStretch()
        x=QPushButton("✕"); x.setFixedSize(32,32); x.setStyleSheet(f"background:transparent;color:{MUTED};border:none;font-size:14px;")
        x.clicked.connect(self.close); bl.addWidget(x); root.addWidget(bar)
        content=QWidget(); cl=QVBoxLayout(content); cl.setContentsMargins(60,40,60,40); cl.setSpacing(20); cl.setAlignment(Qt.AlignCenter)
        cl.addWidget(QLabel("Choose Your Profile",alignment=Qt.AlignCenter,styleSheet=f"font-size:22px;font-weight:700;color:{TEXT};"))
        cl.addWidget(QLabel("Select a profile or create a new one.",alignment=Qt.AlignCenter,styleSheet=f"font-size:13px;color:{MUTED};"))
        self.cards_w=QWidget(); self.cards_l=QHBoxLayout(self.cards_w)
        self.cards_l.setAlignment(Qt.AlignCenter); self.cards_l.setSpacing(20); cl.addWidget(self.cards_w)
        add=QPushButton("＋  New Profile"); add.setFixedWidth(160)
        add.setStyleSheet(f"QPushButton{{background:transparent;border:1px dashed {PURPLE};color:{PURPLE};border-radius:8px;padding:10px;font-weight:600;}}QPushButton:hover{{background:#1a0a2e;color:white;}}")
        add.clicked.connect(self._create); cl.addWidget(add,alignment=Qt.AlignCenter)
        root.addWidget(content); self._load()
    def _load(self):
        for i in reversed(range(self.cards_l.count())):
            w=self.cards_l.itemAt(i).widget()
            if w: w.deleteLater()
        profiles=load_profiles()
        if not profiles:
            self.cards_l.addWidget(QLabel("No profiles yet. Create one!",styleSheet=f"color:{MUTED};font-size:13px;"))
        else:
            for key,p in profiles.items():
                card=ProfileCard(p["display_name"],key); card.clicked.connect(self._login); self.cards_l.addWidget(card)
    def _login(self,key):
        p=load_profiles().get(key,{})
        dlg=PasswordDialog(p.get("display_name",key),self)
        if dlg.exec_()==QDialog.Accepted:
            result=verify_login(key,dlg.password)
            if result:
                global _current_profile; _current_profile=result; self.login_success.emit(result,key)
            else: QMessageBox.warning(self,"Login Failed","Incorrect password.")
    def _create(self):
        dlg=CreateProfileDialog(self)
        if dlg.exec_()==QDialog.Accepted:
            d=dlg.data
            if create_profile(d["username"],d["password"],d["assistant_name"],d["voice"]): self._load()
            else: QMessageBox.warning(self,"Error","Username already exists.")
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton: self._drag=e.globalPos()-self.frameGeometry().topLeft()
    def mouseMoveEvent(self,e):
        if self._drag and e.buttons()==Qt.LeftButton: self.move(e.globalPos()-self._drag)

# ─── Home Screen ──────────────────────────────────────────────────────────────
class HomeScreen(QWidget):
    def __init__(self, profile: dict, parent=None):
        super().__init__(parent); self.setStyleSheet(f"background-color:{BG};")
        lay=QVBoxLayout(self); lay.setAlignment(Qt.AlignCenter); lay.setSpacing(20); lay.setContentsMargins(40,40,40,60)
        self.gif_label=QLabel(); self.gif_label.setAlignment(Qt.AlignCenter)
        gif_path=gfx("Jarvis.gif")
        if os.path.exists(gif_path):
            movie=QMovie(gif_path)
            if movie.isValid(): movie.setScaledSize(QSize(480,270)); self.gif_label.setMovie(movie); movie.start()
        lay.addWidget(self.gif_label)
        self.status_lbl=QLabel(_assistant_status); self.status_lbl.setAlignment(Qt.AlignCenter)
        self.status_lbl.setStyleSheet(f"color:{ACCENT};font-size:15px;font-weight:500;letter-spacing:1px;")
        lay.addWidget(self.status_lbl)
        self.mic_btn=QPushButton("🎤"); self.mic_btn.setFixedSize(80,80); self.mic_btn.setCursor(Qt.PointingHandCursor)
        self._on=False; self._style_mic(); self.mic_btn.clicked.connect(lambda: SetMicrophoneStatus(not _mic_active))
        lay.addWidget(self.mic_btn,alignment=Qt.AlignCenter)
        lay.addWidget(QLabel("Click the mic to activate voice input",alignment=Qt.AlignCenter,styleSheet=f"color:{MUTED};font-size:11px;"))
        signals.status_update.connect(self.status_lbl.setText); signals.mic_toggled.connect(self._on_mic)
    def _style_mic(self):
        if self._on:
            self.mic_btn.setStyleSheet(f"QPushButton{{background-color:{ACCENT};border:3px solid {ACCENT};border-radius:40px;font-size:28px;color:#000;}}")
        else:
            self.mic_btn.setStyleSheet(f"QPushButton{{background-color:{SURFACE};border:2px solid {BORDER};border-radius:40px;font-size:28px;color:{MUTED};}}QPushButton:hover{{border-color:{ACCENT};color:{ACCENT};}}")
    def _on_mic(self,active): self._on=active; self._style_mic()

# ─── Chat Screen ──────────────────────────────────────────────────────────────
class ChatScreen(QWidget):
    def __init__(self, profile: dict, username_key: str, parent=None):
        super().__init__(parent)
        self.username=profile.get("display_name","You")
        self.assistant=profile.get("settings",{}).get("assistant_name","Jarvis")
        self.setStyleSheet(f"background-color:{BG};")
        lay=QVBoxLayout(self); lay.setContentsMargins(20,20,20,20); lay.setSpacing(8)
        lay.addWidget(QLabel("Conversation",styleSheet=f"font-size:16px;font-weight:700;color:{ACCENT};"))
        self.edit=QTextEdit(); self.edit.setReadOnly(True); self.edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.edit.setStyleSheet(f"QTextEdit{{background-color:{SURFACE};color:{TEXT};border:1px solid {BORDER};border-radius:10px;padding:12px;font-size:14px;}}")
        lay.addWidget(self.edit)
        self._load_history(); signals.chat_message.connect(self._append)
    def _load_history(self):
        try:
            with open(os.path.join(DATA_DIR,"ChatLog.json"),"r",encoding="utf-8") as f: history=json.load(f)
            for e in history:
                if e.get("role")=="user": self._append(f"{self.username}: {e.get('content','')}",True)
                elif e.get("role")=="assistant": self._append(f"{self.assistant}: {e.get('content','')}",False)
        except: pass
    def _append(self,text:str,is_user:bool=None):
        cur=self.edit.textCursor(); cur.movePosition(cur.End)
        bf=QTextBlockFormat(); bf.setTopMargin(6); bf.setLeftMargin(8); cur.setBlockFormat(bf)
        cf=QTextCharFormat()
        if is_user is None: is_user=f"{self.username}:" in text
        cf.setForeground(QColor(ACCENT if is_user else TEXT)); cf.setFont(QFont("Segoe UI",11))
        cur.setCharFormat(cf); cur.insertText(text+"\n")
        self.edit.setTextCursor(cur); self.edit.ensureCursorVisible()

# ─── Settings Screen ──────────────────────────────────────────────────────────
class SettingsScreen(QWidget):
    def __init__(self,profile:dict,username_key:str,parent=None):
        super().__init__(parent); self.profile=profile; self.uk=username_key; self.setts=profile.get("settings",{})
        self.setStyleSheet(f"background-color:{BG};")
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("border:none;")
        container=QWidget(); container.setStyleSheet(f"background-color:{BG};")
        form=QVBoxLayout(container); form.setContentsMargins(40,30,40,30); form.setSpacing(22)
        def section(t):
            form.addWidget(QLabel(t,styleSheet=f"font-size:12px;font-weight:700;color:{ACCENT};letter-spacing:1px;"))
            sep=QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet(f"color:{BORDER};"); form.addWidget(sep)
        def row(label,widget):
            r=QHBoxLayout(); lbl=QLabel(label); lbl.setFixedWidth(160); lbl.setStyleSheet(f"color:{MUTED};font-size:13px;")
            r.addWidget(lbl); r.addWidget(widget); form.addLayout(r)
        section("PROFILE")
        self.name_in=QLineEdit(profile.get("display_name","")); row("Display Name",self.name_in)
        self.old_pwd=QLineEdit(); self.old_pwd.setPlaceholderText("Current password"); self.old_pwd.setEchoMode(QLineEdit.Password); row("Current Password",self.old_pwd)
        self.new_pwd=QLineEdit(); self.new_pwd.setPlaceholderText("Leave blank to keep"); self.new_pwd.setEchoMode(QLineEdit.Password); row("New Password",self.new_pwd)
        section("ASSISTANT")
        self.asst_in=QLineEdit(self.setts.get("assistant_name","Jarvis")); row("Assistant Name",self.asst_in)
        self.v_combo=QComboBox(); cur=self.setts.get("voice","en-US-JennyNeural")
        for i,(lbl,val) in enumerate(VOICES):
            self.v_combo.addItem(lbl)
            if val==cur: self.v_combo.setCurrentIndex(i)
        row("Voice",self.v_combo)
        section("API KEYS")
        env=dotenv_values(".env")
        self.groq_in=QLineEdit(self.setts.get("groq_api_key") or env.get("GroqAPIKey","")); self.groq_in.setEchoMode(QLineEdit.Password); row("Groq API Key",self.groq_in)
        self.hf_in=QLineEdit(self.setts.get("huggingface_api_key") or env.get("HuggingFaceAPIKey","")); self.hf_in.setEchoMode(QLineEdit.Password); row("HuggingFace Key",self.hf_in)
        save_btn=QPushButton("Save Changes"); save_btn.setFixedWidth(160)
        save_btn.setStyleSheet(f"background-color:{ACCENT};color:#000;font-weight:700;border:none;padding:12px;border-radius:8px;font-size:14px;")
        save_btn.clicked.connect(self._save); form.addWidget(save_btn,alignment=Qt.AlignLeft)
        self.feedback=QLabel(""); self.feedback.setStyleSheet(f"font-size:12px;color:{SUCCESS};"); form.addWidget(self.feedback)
        scroll.setWidget(container); outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(scroll)
    def _save(self):
        name=self.name_in.text().strip()
        if name and name!=self.profile.get("display_name"): update_display_name(self.uk,name); self.profile["display_name"]=name
        if self.new_pwd.text():
            if not change_password(self.uk,self.old_pwd.text(),self.new_pwd.text()):
                self.feedback.setStyleSheet(f"font-size:12px;color:{DANGER};"); self.feedback.setText("Current password is incorrect."); return
        new={"assistant_name":self.asst_in.text().strip() or "Jarvis","voice":VOICES[self.v_combo.currentIndex()][1],"groq_api_key":self.groq_in.text().strip(),"huggingface_api_key":self.hf_in.text().strip()}
        update_settings(self.uk,**new); self.profile["settings"].update(new)
        try:
            if new["groq_api_key"]: set_key(".env","GroqAPIKey",new["groq_api_key"])
            if new["huggingface_api_key"]: set_key(".env","HuggingFaceAPIKey",new["huggingface_api_key"])
            set_key(".env","AssistantVoice",new["voice"])
        except: pass
        self.feedback.setStyleSheet(f"font-size:12px;color:{SUCCESS};"); self.feedback.setText("✓ Settings saved.")

# ─── Sidebar ──────────────────────────────────────────────────────────────────
class SideBar(QWidget):
    nav_clicked = pyqtSignal(int)
    def __init__(self, profile: dict, parent=None):
        super().__init__(parent); self.setFixedWidth(200)
        self.setStyleSheet(f"background-color:{SIDEBAR};border-right:1px solid {BORDER};")
        lay=QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        brand=QWidget(); brand.setFixedHeight(64); brand.setStyleSheet(f"background-color:{SIDEBAR};")
        bl=QVBoxLayout(brand); bl.setAlignment(Qt.AlignCenter)
        bl.addWidget(QLabel("JARVIS AI",alignment=Qt.AlignCenter,styleSheet=f"color:{ACCENT};font-size:15px;font-weight:800;letter-spacing:3px;"))
        lay.addWidget(brand)
        sep=QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet(f"color:{BORDER};margin:0 12px;"); lay.addWidget(sep)
        lay.addSpacing(12)
        self._btns=[]
        for label,idx in [("🏠  Home",0),("💬  Chat",1),("⚙️  Settings",2)]:
            btn=QPushButton(label); btn.setFixedHeight(44); btn.setStyleSheet(self._style(False))
            btn.clicked.connect(lambda _,i=idx: self._nav(i)); lay.addWidget(btn); self._btns.append(btn)
        lay.addStretch()
        sep2=QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setStyleSheet(f"color:{BORDER};margin:0 12px;"); lay.addWidget(sep2)
        uw=QWidget(); uw.setFixedHeight(60); ul=QHBoxLayout(uw); ul.setContentsMargins(14,0,14,0); ul.setSpacing(10)
        av=QLabel(profile.get("display_name","?")[0].upper()); av.setFixedSize(34,34); av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet(f"background-color:{PURPLE};color:white;border-radius:17px;font-weight:700;font-size:13px;")
        ul.addWidget(av); ul.addWidget(QLabel(profile.get("display_name","User"),styleSheet=f"color:{TEXT};font-size:13px;font-weight:600;"))
        lay.addWidget(uw); self._nav(0)
    def _style(self,active):
        if active: return f"QPushButton{{background-color:#1a1a2e;border-left:3px solid {ACCENT};border-top:none;border-right:none;border-bottom:none;color:{ACCENT};text-align:left;padding-left:20px;font-size:13px;font-weight:600;border-radius:0px;}}"
        return f"QPushButton{{background-color:transparent;border:none;color:{MUTED};text-align:left;padding-left:24px;font-size:13px;border-radius:0px;}}QPushButton:hover{{background-color:#15152a;color:{TEXT};}}"
    def _nav(self,idx):
        for i,b in enumerate(self._btns): b.setStyleSheet(self._style(i==idx))
        self.nav_clicked.emit(idx)

# ─── Top Bar ──────────────────────────────────────────────────────────────────
class TopBar(QWidget):
    def __init__(self, parent_win, profile: dict):
        super().__init__(parent_win); self.pw=parent_win; self.setFixedHeight(44); self._drag=None
        self.setStyleSheet(f"background-color:{SIDEBAR};border-bottom:1px solid {BORDER};")
        lay=QHBoxLayout(self); lay.setContentsMargins(16,0,8,0); lay.setSpacing(6)
        lay.addWidget(QLabel(f"Welcome, {profile.get('display_name','User')}",styleSheet=f"color:{MUTED};font-size:12px;"))
        lay.addStretch()
        for txt,act in [("─","min"),("□","max"),("✕","close")]:
            b=QPushButton(txt); b.setFixedSize(32,32); b.setStyleSheet(f"background:transparent;color:{MUTED};border:none;font-size:13px;border-radius:4px;")
            if act=="min": b.clicked.connect(parent_win.showMinimized)
            elif act=="max": b.clicked.connect(lambda: parent_win.showNormal() if parent_win.isMaximized() else parent_win.showMaximized())
            else: b.clicked.connect(parent_win.close)
            lay.addWidget(b)
    def mousePressEvent(self,e):
        if e.button()==Qt.LeftButton: self._drag=e.globalPos()-self.pw.frameGeometry().topLeft()
    def mouseMoveEvent(self,e):
        if self._drag and e.buttons()==Qt.LeftButton: self.pw.move(e.globalPos()-self._drag)

# ─── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, profile: dict, username_key: str):
        super().__init__()
        self.setWindowTitle(f"Jarvis AI — {profile.get('display_name','User')}")
        self.setWindowFlags(Qt.FramelessWindowHint); self.setStyleSheet(GLOBAL_STYLE)
        self.setMinimumSize(900,600); self.resize(1200,750)
        central=QWidget(); self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(TopBar(self, profile))
        body=QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)
        self.sidebar=SideBar(profile); body.addWidget(self.sidebar)
        self.stack=QStackedWidget()
        self.home=HomeScreen(profile); self.chat=ChatScreen(profile,username_key); self.setts=SettingsScreen(profile,username_key)
        self.stack.addWidget(self.home); self.stack.addWidget(self.chat); self.stack.addWidget(self.setts)
        body.addWidget(self.stack)
        bw=QWidget(); bw.setLayout(body); root.addWidget(bw)
        self.sidebar.nav_clicked.connect(self.stack.setCurrentIndex)

# ─── Entry Point ──────────────────────────────────────────────────────────────
def GraphicalUserInterface():
    app = QApplication(sys.argv)
    app.setStyleSheet(GLOBAL_STYLE)
    auth = AuthWindow()
    _ref = {}

    def on_login(profile: dict, key: str):
        win = MainWindow(profile, key)
        _ref["win"] = win
        screen = QApplication.primaryScreen().availableGeometry()
        win.setGeometry(screen.x()+(screen.width()-1200)//2, screen.y()+(screen.height()-750)//2, 1200, 750)
        win.show()
        auth.close()

    auth.login_success.connect(on_login)
    screen = QApplication.primaryScreen().availableGeometry()
    auth.setGeometry(screen.x()+(screen.width()-700)//2, screen.y()+(screen.height()-520)//2, 700, 520)
    auth.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    GraphicalUserInterface()
