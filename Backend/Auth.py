import json
import hashlib
import os
import secrets

PROFILES_PATH = os.path.join("Data", "profiles.json")

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()

def load_profiles() -> dict:
    if not os.path.exists(PROFILES_PATH):
        return {}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def _save(profiles: dict) -> None:
    os.makedirs(os.path.dirname(PROFILES_PATH), exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=4)

def create_profile(username: str, password: str,
                   assistant_name: str = "Jarvis",
                   voice: str = "en-US-JennyNeural") -> bool:
    """Create a new profile. Returns False if username already taken."""
    profiles = load_profiles()
    key = username.lower().strip()
    if key in profiles:
        return False
    salt = secrets.token_hex(16)
    profiles[key] = {
        "display_name": username.strip(),
        "salt": salt,
        "password_hash": _hash(password, salt),
        "settings": {
            "assistant_name": assistant_name,
            "voice": voice,
            "groq_api_key": "",
            "huggingface_api_key": "",
        },
    }
    _save(profiles)
    return True

def verify_login(username: str, password: str) -> dict | None:
    """Return profile dict on success, None on failure."""
    profiles = load_profiles()
    profile = profiles.get(username.lower().strip())
    if not profile:
        return None
    if _hash(password, profile["salt"]) == profile["password_hash"]:
        return profile
    return None

def update_settings(username: str, **kwargs) -> bool:
    """Update any key(s) inside a profile's settings dict."""
    profiles = load_profiles()
    key = username.lower().strip()
    if key not in profiles:
        return False
    profiles[key]["settings"].update(kwargs)
    _save(profiles)
    return True

def update_display_name(username: str, new_name: str) -> bool:
    profiles = load_profiles()
    key = username.lower().strip()
    if key not in profiles:
        return False
    profiles[key]["display_name"] = new_name.strip()
    _save(profiles)
    return True

def change_password(username: str, old_password: str, new_password: str) -> bool:
    if not verify_login(username, old_password):
        return False
    profiles = load_profiles()
    key = username.lower().strip()
    salt = secrets.token_hex(16)
    profiles[key]["salt"] = salt
    profiles[key]["password_hash"] = _hash(new_password, salt)
    _save(profiles)
    return True

def delete_profile(username: str, password: str) -> bool:
    if not verify_login(username, password):
        return False
    profiles = load_profiles()
    profiles.pop(username.lower().strip(), None)
    _save(profiles)
    return True
