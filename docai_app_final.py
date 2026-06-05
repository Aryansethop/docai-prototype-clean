import streamlit as st
import requests
import json
import hashlib
import os
import re
import time
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta
from urllib.parse import quote
import html
import unicodedata
from collections import defaultdict
from supabase import create_client
import threading

# ==================== SENTRY (OPTIONAL) ====================
try:
    SENTRY_DSN = st.secrets.get("SENTRY_DSN", "")
    if SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=1.0,
            environment="production"
        )
except:
    pass

# ==================== GROVE AI DESIGN SYSTEM CSS ====================
grove_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,100..900;1,100..900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400&display=swap');

:root {
  --color-canvas-white: #ffffff;
  --color-grove-green: #0b835c;
  --color-nightfall-black: #000000;
  --color-dark-forrest: #1c2b27;
  --color-body-text-charcoal: #1c1c1e;
  --color-muted-ash: #303033;
  --color-card-mist: #eff1f6;
  --color-shadow-gray: #bfbfbf;
  --color-supporting-stone: #676768;
  --font-geist: 'Inter', ui-sans-serif, system-ui, sans-serif;
  --font-libre-caslon: 'Libre Caslon Text', Georgia, serif;
  --radius-cards: 20px;
  --radius-buttons: 16px;
  --radius-pill: 40px;
  --spacing-12: 12px;
  --spacing-16: 16px;
  --spacing-20: 20px;
  --spacing-24: 24px;
  --spacing-32: 32px;
  --spacing-40: 40px;
  --spacing-48: 48px;
}

html, body, .stApp { background-color: var(--color-canvas-white); }
.main .block-container { padding-top: 1rem; padding-bottom: 4rem; max-width: 1200px; }
h1, h2, h3, .stTitle { font-family: var(--font-libre-caslon); font-weight: 400; color: var(--color-nightfall-black); }
h1 { font-size: 40px; letter-spacing: -1.44px; line-height: 1.07; }
h2 { font-size: 32px; letter-spacing: -0.9px; line-height: 1.14; }
p, li, .stMarkdown, div:not(.stButton) > p { font-family: var(--font-geist); font-size: 16px; line-height: 1.25; color: var(--color-body-text-charcoal); }
[data-testid="stSidebar"] { background-color: var(--color-card-mist) !important; border-right: none !important; }
.stChatInput input { background-color: var(--color-canvas-white) !important; color: var(--color-nightfall-black) !important; border: 1px solid var(--color-shadow-gray) !important; border-radius: var(--radius-pill) !important; padding: 12px 20px !important; font-family: var(--font-geist) !important; font-size: 16px !important; }
.stChatInput input:focus { outline: none !important; border-color: var(--color-grove-green) !important; box-shadow: 0 0 0 2px rgba(11, 131, 92, 0.2) !important; }
[data-testid="stChatMessageUser"] { background-color: var(--color-card-mist) !important; border-radius: var(--radius-cards) !important; padding: 12px 16px !important; }
[data-testid="stChatMessageUser"] p { color: var(--color-nightfall-black) !important; }
.stButton > button { background-color: var(--color-grove-green) !important; color: white !important; border: none !important; border-radius: var(--radius-buttons) !important; padding: 12px 20px !important; font-family: var(--font-geist) !important; font-weight: 500 !important; font-size: 14px !important; }
.stButton > button:hover { background-color: #0a6e4e !important; cursor: pointer !important; }
.streamlit-expanderHeader { background-color: var(--color-card-mist) !important; border-radius: var(--radius-cards) !important; color: var(--color-nightfall-black) !important; }
.stTabs [data-baseweb="tab"][aria-selected="true"] { background-color: var(--color-dark-forrest) !important; color: white !important; }
[data-testid="stMetric"] { background-color: var(--color-card-mist); border-radius: var(--radius-cards); padding: var(--spacing-16); }
.bottom-nav { position: fixed; bottom: 0; left: 0; right: 0; background-color: #ffffff; border-top: 1px solid #eff1f6; display: flex; justify-content: space-around; padding: 10px 0; z-index: 100; }
.nav-item { color: #676768; text-align: center; font-family: 'Inter', sans-serif; font-size: 12px; text-decoration: none; }
.nav-item:hover { color: #0b835c; }
.main-content { margin-bottom: 70px; }
"""
st.markdown(grove_css, unsafe_allow_html=True)

# ==================== EMERGENCY NUMBERS ====================
EMERGENCY_NUMBERS = {
    "IN": {"ambulance": "108", "police": "100", "fire": "101", "name": "India"},
    "US": {"ambulance": "911", "police": "911", "fire": "911", "name": "USA"},
    "GB": {"ambulance": "999", "police": "999", "fire": "999", "name": "UK"},
    "default": {"ambulance": "112", "police": "112", "fire": "112", "name": "International"}
}

def detect_country():
    try:
        response = requests.get('http://ip-api.com/json/', timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return data.get('countryCode', 'IN')
    except:
        pass
    return "IN"

country_code = detect_country()
emergency = EMERGENCY_NUMBERS.get(country_code, EMERGENCY_NUMBERS["default"])

# ==================== RATE LIMITING ====================
_rate_limit_store = defaultdict(list)

def check_rate_limit(username):
    """Returns True if request is allowed, False if rate limit exceeded."""
    now = time.time()
    _rate_limit_store[username] = [t for t in _rate_limit_store[username] if now - t < 60]
    if len(_rate_limit_store[username]) >= 10:
        return False
    _rate_limit_store[username].append(now)
    return True

# ==================== SUPABASE CONNECTION (Asia Only) ====================
def get_supabase_client():
    """Create Supabase client using Asia database only."""
    try:
        SUPABASE_URL = st.secrets["SUPABASE_URL"]
        SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase connection failed: {e}")
        st.stop()

# ==================== DATABASE FUNCTIONS ====================
def create_audit_log(user_id, user_input, ai_output, emergency_triggered=False, confidence_score=None):
    supabase = get_supabase_client()
    try:
        supabase.table("audit_logs").insert({
            "user_id": user_id,
            "user_input": user_input[:500],
            "ai_output": ai_output[:1000],
            "emergency_triggered": emergency_triggered,
            "confidence_score": confidence_score,
            "created_at": datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"Audit log error: {e}")

def log_guardrail(user_id, user_input, ai_output, was_blocked, block_reason=""):
    supabase = get_supabase_client()
    try:
        supabase.table("guardrails_log").insert({
            "user_id": user_id,
            "user_input": user_input[:500],
            "ai_output": ai_output[:500] if ai_output else "",
            "was_blocked": was_blocked,
            "block_reason": block_reason
        }).execute()
    except Exception as e:
        print(f"Guardrail log error: {e}")

def log_data_lineage(user_id, query, response, source):
    supabase = get_supabase_client()
    try:
        supabase.table("data_lineage").insert({
            "user_id": user_id,
            "query": query[:500],
            "response": response[:1000],
            "source": source
        }).execute()
    except Exception as e:
        print(f"Lineage log error: {e}")

def save_feedback(user_id, response_id, rating, comment=""):
    supabase = get_supabase_client()
    try:
        supabase.table("feedback").insert({
            "user_id": user_id,
            "response_id": response_id,
            "rating": rating,
            "comment": comment[:200] if comment else ""
        }).execute()
        return True
    except Exception as e:
        print(f"Feedback error: {e}")
        return False

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def calculate_bmi(height, weight):
    if height and weight and height > 0:
        bmi = weight / ((height/100) ** 2)
        if bmi < 18.5:
            return f"{bmi:.1f} (Underweight)"
        elif bmi < 25:
            return f"{bmi:.1f} (Normal)"
        elif bmi < 30:
            return f"{bmi:.1f} (Overweight)"
        else:
            return f"{bmi:.1f} (Obese)"
    return "Not calculated"

# ==================== USER AUTHENTICATION ====================
def create_user(username, email, phone, password):
    supabase = get_supabase_client()
    try:
        hashed_pw = hash_password(password)
        result = supabase.table("users").insert({
            "username": username,
            "email": email,
            "phone": phone,
            "password": hashed_pw
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Error creating user: {e}")
        return None

def get_user_by_email(email):
    supabase = get_supabase_client()
    try:
        result = supabase.table("users").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None
    except:
        return None

def get_user_by_username(username):
    supabase = get_supabase_client()
    try:
        result = supabase.table("users").select("*").eq("username", username).execute()
        return result.data[0] if result.data else None
    except:
        return None

def verify_login(email, password):
    supabase = get_supabase_client()
    try:
        result = supabase.table("users").select("*").eq("email", email).execute()
        user = result.data[0] if result.data else None
        if user and user["password"] == hash_password(password):
            return user
    except:
        pass
    return None

def save_profile(user_id, profile_data):
    supabase = get_supabase_client()
    try:
        profile_data["user_id"] = user_id
        existing = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        if existing.data:
            result = supabase.table("profiles").update(profile_data).eq("user_id", user_id).execute()
        else:
            result = supabase.table("profiles").insert(profile_data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"Save profile error: {e}")
        return None

def get_profile(user_id):
    supabase = get_supabase_client()
    try:
        result = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None
    except:
        return None

def add_medication_to_db(user_id, medicine_name, dosage, reminder_time, user_email):
    supabase = get_supabase_client()
    try:
        result = supabase.table("medications").insert({
            "user_id": user_id,
            "medicine_name": medicine_name,
            "dosage": dosage,
            "reminder_time": reminder_time
        }).execute()
        if result.data:
            send_reminder_email(user_email, medicine_name, dosage, reminder_time)
        return result.data[0] if result.data else None
    except:
        return None

def get_user_medications(user_id):
    supabase = get_supabase_client()
    try:
        result = supabase.table("medications").select("*").eq("user_id", user_id).execute()
        return result.data
    except:
        return []

def add_reminder_to_db(user_id, medicine, dosage, reminder_time):
    supabase = get_supabase_client()
    try:
        result = supabase.table("medications").insert({
            "user_id": user_id,
            "medicine_name": medicine,
            "dosage": dosage,
            "reminder_time": reminder_time
        }).execute()
        return result.data[0] if result.data else None
    except:
        return None

def get_missed_doses(user_id):
    supabase = get_supabase_client()
    try:
        current_time = datetime.now().strftime("%H:%M")
        meds = supabase.table("medications").select("*").eq("user_id", user_id).execute()
        missed = []
        for med in meds.data:
            reminder = med.get("reminder_time", "")
            if reminder and reminder < current_time:
                missed.append(med)
        return missed
    except:
        return []

# ==================== EMAIL ====================
def send_reminder_email(user_email, medicine_name, dosage, reminder_time):
    try:
        EMAIL_FROM = st.secrets.get("EMAIL_FROM", "")
        EMAIL_PASSWORD = st.secrets.get("EMAIL_PASSWORD", "")
        if not EMAIL_FROM or not EMAIL_PASSWORD:
            return False
        subject = f"💊 DOCAI Reminder: Time to take {medicine_name}"
        body = f"""
Hello,

This is a reminder that it's time to take your medication:

💊 Medicine: {medicine_name}
💊 Dosage: {dosage}
⏰ Time: {reminder_time}

Stay healthy!

- DOCAI Medical Assistant
        """
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = user_email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ==================== OPENROUTER API ====================
try:
    OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
    if not OPENROUTER_API_KEY:
        st.error("OpenRouter API key not configured.")
        st.stop()
except KeyError:
    st.error("OpenRouter API key not found in secrets.")
    st.stop()

# ==================== SAFETY & VALIDATION ====================
EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "can't breathe", "difficulty breathing",
    "severe bleeding", "unconscious", "passed out", "seizure", "stroke",
    "choking", "suicide", "kill myself", "overdose", "emergency", "dying"
]

def check_emergency(user_input):
    user_lower = user_input.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in user_lower:
            return True, f"""🚨 **EMERGENCY DETECTED** 🚨

**Please call your local emergency number immediately: {emergency['ambulance']}**

Do not wait for AI advice. If you are with someone, ask them to call help.

⚠️ This is an automated safety block."""
    return False, None

def validate_input(user_input):
    if not user_input or not isinstance(user_input, str):
        return "", False
    cleaned = html.escape(user_input)
    cleaned = unicodedata.normalize('NFKD', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if len(cleaned) > 2000:
        cleaned = cleaned[:2000] + "... [truncated]"
    dangerous = re.search(r'(<script|javascript:|onload=|onerror=|alert\(|eval\(|exec\()', cleaned, re.IGNORECASE)
    if dangerous:
        return "Invalid input detected. Please rephrase.", False
    return cleaned, True

def validate_output_safety(ai_response):
    emergency_patterns = [
        "heart attack", "cardiac arrest", "stop breathing", "unconscious",
        "overdose", "suicide", "severe bleeding", "can't breathe", "choking"
    ]
    for pat in emergency_patterns:
        if pat.lower() in ai_response.lower():
            return False, pat, "emergency"
    return True, "safe", "normal"

def evaluate_confidence(user_input, ai_response):
    score = 50
    if len(ai_response) > 200:
        score += 15
    elif len(ai_response) < 50:
        score -= 20
    if "consult your doctor" in ai_response.lower():
        score += 10
    if re.search(r'\d+\s*(mg|mcg|g|ml|tablet|pill)', ai_response.lower()):
        score += 15
    if any(phrase in ai_response.lower() for phrase in ["maybe", "could be", "not sure", "i think"]):
        score -= 15
    return max(0, min(100, score))

def format_with_confidence(response, score):
    if score < 60:
        return response + f"\n\n⚠️ **Confidence: {score}%** — Low confidence. Please consult a doctor."
    elif score < 85:
        return response + f"\n\n📊 **Confidence: {score}%** — Good, but verify with a healthcare provider."
    else:
        return response + f"\n\n✅ **Confidence: {score}%** — High confidence, but always consult a doctor."

def fallback_response():
    return "⚠️ I'm experiencing high demand. Please try again.\n\n💙 *Always consult your doctor.*"

def call_openrouter_with_retry(prompt, username, max_retries=3):
    if not check_rate_limit(username):
        return "⚠️ **Rate limit exceeded.** Please wait a moment before sending more messages."
    for attempt in range(max_retries):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://docai-app.com",
                    "X-Title": "DOCAI Medical Assistant"
                },
                json={
                    "model": "openai/gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000
                },
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                if "choices" in data:
                    raw_response = data["choices"][0]["message"]["content"]
                    confidence = evaluate_confidence(prompt, raw_response)
                    return format_with_confidence(raw_response, confidence)
            elif response.status_code == 429:
                wait_time = (attempt + 1) * 2
                time.sleep(wait_time)
                continue
            else:
                return fallback_response()
        except Exception as e:
            print(f"OpenRouter error: {e}")
            if attempt == max_retries - 1:
                return fallback_response()
            time.sleep(2)
    return fallback_response()

def get_ai_response(user_query, user_profile, chat_history, username, user_id):
    cleaned_query, valid = validate_input(user_query)
    if not valid:
        return cleaned_query
    
    is_emergency, emg_msg = check_emergency(cleaned_query)
    if is_emergency:
        create_audit_log(user_id, cleaned_query, emg_msg, emergency_triggered=True)
        return emg_msg
    
    profile_text = ""
    if user_profile:
        profile_text = f"""
USER HEALTH PROFILE:
- Age: {user_profile.get('age', 'Not provided')}
- Blood Type: {user_profile.get('blood_type', 'Not provided')}
- Conditions: {user_profile.get('conditions', 'None reported')}
- Allergies: {user_profile.get('allergies', 'None reported')}
"""
    history_text = "\n".join([f"{m['role']}: {m['content'][:150]}" for m in chat_history[-6:]])
    prompt = f"""You are a caring, professional medical AI assistant.

{profile_text}
Previous conversation:
{history_text}
User: {cleaned_query}

Provide specific medicine name, uses, dosage, timing, side effects, warnings. Always say consult your doctor."""
    
    raw_response = call_openrouter_with_retry(prompt, username)
    
    safe, reason, severity = validate_output_safety(raw_response)
    if not safe and severity == "emergency":
        log_guardrail(user_id, cleaned_query, raw_response, True, reason)
        create_audit_log(user_id, cleaned_query, raw_response, emergency_triggered=True)
        return f"🚨 **EMERGENCY DETECTED** 🚨\n\nEmergency detected: '{reason}'\n\n**CALL {emergency['ambulance']} IMMEDIATELY**\n\nDo not wait. Do not rely on AI for emergencies."
    elif not safe:
        log_guardrail(user_id, cleaned_query, raw_response, True, reason)
        create_audit_log(user_id, cleaned_query, raw_response, emergency_triggered=False)
        return f"⚠️ **Safety Notice**\n\nBlocked: '{reason}'\n\nPlease consult a doctor for specific medical advice."
    
    log_guardrail(user_id, cleaned_query, raw_response, False, "")
    log_data_lineage(user_id, cleaned_query, raw_response, "openrouter_api")
    create_audit_log(user_id, cleaned_query, raw_response)
    return raw_response

def calculate_dosage(user_input):
    patterns = [r'(\d+)\s*mg.*?(?:but|need|have).*?(\d+)\s*mg', r'have (\d+)\s*mg.*?need (\d+)\s*mg']
    for pattern in patterns:
        match = re.search(pattern, user_input.lower())
        if match:
            available = int(match.group(1))
            needed = int(match.group(2))
            pills = needed / available
            if pills == int(pills):
                return f"""💊 **Dosage Calculation**

You have {available}mg tablets. You need {needed}mg.

**Take {int(pills)} tablets.**

⚠️ Always confirm with your doctor or pharmacist."""
            else:
                return f"""💊 **Dosage Calculation**

You have {available}mg tablets. You need {needed}mg.

**Take {pills:.1f} tablets.**

⚠️ Consult your pharmacist."""
    return None

# ==================== TRANSLATION ====================
LANGUAGES = {"en": "English", "hi": "हिन्दी", "ru": "Русский", "zh": "中文", "es": "Español"}

def translate_text(text, target_lang):
    if target_lang == "en" or not target_lang or not text:
        return text
    try:
        prompt = f"Translate the following medical information to {LANGUAGES.get(target_lang, target_lang)}. Keep medical terms accurate. Return only the translation:\n\n{text[:1500]}"
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-3.5-turbo",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 1500
            },
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Translation error: {e}")
    return text

# ==================== NEWS ====================
def get_daily_news():
    try:
        import feedparser
        feed = feedparser.parse("https://www.who.int/rss-feeds/news-english.xml")
        news_items = []
        for entry in feed.entries[:5]:
            news_items.append(f"📢 **{entry.title}**\n{entry.summary[:150]}...\n[Read more]({entry.link})\n")
        return news_items if news_items else ["Unable to fetch news at this time."]
    except ImportError:
        return ["News feature requires 'feedparser' package. Install with: pip install feedparser"]
    except Exception as e:
        print(f"News error: {e}")
        return ["Unable to fetch news. Please visit WHO website directly."]

# ==================== VOICE INPUT ====================
VOICE_HTML = """
<div style="position: fixed; bottom: 80px; right: 20px; z-index: 1000;">
    <button id="voiceBtn" style="background-color: #0b835c; color: white; border: none; border-radius: 40px; width: 55px; height: 55px; font-size: 24px; cursor: pointer; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
        🎤
    </button>
</div>
<script>
const voiceBtn = document.getElementById('voiceBtn');
if (voiceBtn) {
    voiceBtn.addEventListener('click', () => {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
            const recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                const inputField = document.querySelector('input[type="text"]');
                if (inputField) {
                    inputField.value = transcript;
                    inputField.dispatchEvent(new Event('input', { bubbles: true }));
                }
            };
            recognition.start();
        } else {
            alert('Voice input not supported. Please use Chrome.');
        }
    });
}
</script>
"""
st.markdown(VOICE_HTML, unsafe_allow_html=True)

# ==================== STREAMLIT UI ====================
st.set_page_config(page_title="DOCAI - Medical Intelligence", page_icon="⚕️", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_profile" not in st.session_state:
    st.session_state.user_profile = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_language" not in st.session_state:
    st.session_state.selected_language = "en"
if "current_page" not in st.session_state:
    st.session_state.current_page = "chat"
if "news_shown" not in st.session_state:
    st.session_state.news_shown = False

# ==================== LOGIN PAGE ====================
if not st.session_state.logged_in:
    st.title("⚕️ DOCAI")
    st.markdown("### Medical Intelligence for Every Human")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""✅ **Features:**
- 💊 Medicine information for any disease
- 🩺 Symptoms, causes, treatments
- 🌍 100+ countries emergency numbers
- 🗣️ Voice input available
- 📄 Upload medical reports
- 💊 Medication tracker with reminders
- 🩸 BMI calculator
- 📚 NHS, MalaCards, PubMed, MedlinePlus
- 📰 Daily health news updates
""")
    with col2:
        st.markdown("""✅ **Ask about:**
- "What medicine for diabetes type 2?"
- "Paracetamol dosage for adults"
- "I have 200mg but need 500mg"
- "Symptoms of dengue fever"
- "Treatment for malaria"
""")
    
    tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign Up"])
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email or Phone")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                user = verify_login(email, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.username = user["username"]
                    st.session_state.user_id = user["id"]
                    st.session_state.user_email = user["email"]
                    profile = get_profile(user["id"])
                    st.session_state.user_profile = profile if profile else {}
                    st.success("✅ Welcome back!")
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    
    with tab2:
        with st.form("signup_form"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            phone = st.text_input("Phone Number")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm", type="password")
            if st.form_submit_button("Sign Up"):
                if password != confirm:
                    st.error("Passwords don't match")
                elif len(password) < 4:
                    st.error("Password too short")
                else:
                    existing = get_user_by_username(username)
                    if existing:
                        st.error("Username already exists")
                    else:
                        user = create_user(username, email, phone, password)
                        if user:
                            st.session_state.logged_in = True
                            st.session_state.username = username
                            st.session_state.user_id = user["id"]
                            st.session_state.user_email = user["email"]
                            st.session_state.user_profile = {}
                            st.success("✅ Account created!")
                            st.rerun()
                        else:
                            st.error("Error creating account")
    st.stop()

# ==================== MEDICAL PROFILE ====================
if not st.session_state.user_profile:
    st.title("📋 Complete Your Medical Profile")
    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input("Age", min_value=0, max_value=120, value=30)
            gender = st.selectbox("Gender", ["Male", "Female", "Other"])
            blood_type = st.selectbox("Blood Type", ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Don't know"])
            height = st.number_input("Height (cm)", min_value=50, max_value=250, value=170)
        with col2:
            weight = st.number_input("Weight (kg)", min_value=10, max_value=300, value=70)
            bmi = calculate_bmi(height, weight)
            st.info(f"📊 **Your BMI:** {bmi}")
            conditions = st.text_area("Medical Conditions", placeholder="e.g., diabetes, high blood pressure")
            allergies = st.text_area("Allergies", placeholder="e.g., penicillin")
        
        family_history = st.text_area("Family Medical History")
        medications_list = st.text_area("Current Medications")
        
        if st.form_submit_button("💾 Save Profile"):
            profile_data = {
                "blood_type": blood_type if blood_type != "Don't know" else "",
                "age": age,
                "gender": gender,
                "height": height,
                "weight": weight,
                "bmi": bmi,
                "conditions": conditions,
                "allergies": allergies,
                "family_history": family_history,
                "medications_list": medications_list
            }
            save_profile(st.session_state.user_id, profile_data)
            st.session_state.user_profile = profile_data
            st.success("✅ Profile saved!")
            st.rerun()
    st.stop()

# ==================== MAIN APP ====================
username = st.session_state.username
user_id = st.session_state.user_id
profile = st.session_state.user_profile

with st.sidebar:
    st.title(f"👋 {username}")
    st.markdown(f"**🚑 Emergency: {emergency['ambulance']}**")
    st.markdown("---")
    if profile:
        st.info(f"🩸 Blood: {profile.get('blood_type', 'N/A')}")
        height_val = profile.get('height', 170)
        weight_val = profile.get('weight', 70)
        bmi_val = calculate_bmi(height_val, weight_val)
        st.info(f"📏 BMI: {bmi_val}")
    lang = st.selectbox("🌐 Language", list(LANGUAGES.keys()), format_func=lambda x: LANGUAGES[x], index=0)
    st.session_state.selected_language = lang
    st.markdown("---")
    st.markdown("### 📚 Trusted Sources")
    st.markdown("✅ NHS inform | MalaCards | PubMed | MedlinePlus")
    st.markdown("---")
    
    st.markdown("### 📰 Daily Health News")
    if st.button("🔄 Refresh News"):
        st.session_state.news_shown = False
    if not st.session_state.news_shown:
        news = get_daily_news()
        for item in news:
            st.markdown(item)
        st.session_state.news_shown = True
    
    st.markdown("---")
    if st.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.user_id = None
        st.session_state.user_email = None
        st.session_state.user_profile = None
        st.session_state.messages = []
        st.rerun()

# ==================== BOTTOM NAVIGATION ====================
st.markdown('<div class="main-content">', unsafe_allow_html=True)
nav_col1, nav_col2, nav_col3, nav_col4, nav_col5 = st.columns(5)
with nav_col1:
    if st.button("💬 Chat", use_container_width=True):
        st.session_state.current_page = "chat"
with nav_col2:
    if st.button("💊 Meds", use_container_width=True):
        st.session_state.current_page = "medications"
with nav_col3:
    if st.button("📋 Profile", use_container_width=True):
        st.session_state.current_page = "profile"
with nav_col4:
    if st.button("🔍 Search", use_container_width=True):
        st.session_state.current_page = "search"
with nav_col5:
    if st.button("📞 Emergency", use_container_width=True):
        st.session_state.current_page = "emergency"
st.markdown("---")

# ==================== CHAT PAGE ====================
if st.session_state.current_page == "chat":
    st.title("🤖 Medical AI Assistant 💙")
    st.markdown(f"*Emergency: {emergency['ambulance']} | Upload reports, ask about medicines*")
    
    uploaded_file = st.file_uploader("📄 Upload medical report (optional)", type=["pdf", "png", "jpg", "txt"])
    if uploaded_file:
        st.success(f"✅ {uploaded_file.name} uploaded! AI will consider it.")
    
    st.markdown("😊 😷 🩺 💊 🩸 🧠 ❤️ 💙")
    
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            display_text = translate_text(msg["content"], st.session_state.selected_language) if st.session_state.selected_language != "en" else msg["content"]
            st.markdown(display_text)
            if msg["role"] == "assistant":
                fb_col1, fb_col2 = st.columns(2)
                with fb_col1:
                    if st.button("👍 Helpful", key=f"up_{idx}"):
                        save_feedback(user_id, f"resp_{idx}", 1)
                        st.success("Thanks for your feedback!")
                with fb_col2:
                    if st.button("👎 Not Helpful", key=f"down_{idx}"):
                        save_feedback(user_id, f"resp_{idx}", -1)
                        st.warning("Feedback recorded. We'll improve!")
    
    user_input = st.chat_input("Ask about any disease, medicine, or symptom... 💬")
    
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        
        dosage_response = calculate_dosage(user_input)
        with st.chat_message("assistant"):
            if dosage_response:
                response = dosage_response
                st.markdown(response)
            else:
                with st.spinner("🤖 AI is thinking..."):
                    response = get_ai_response(user_input, profile, st.session_state.messages, username, user_id)
                    translated = translate_text(response, st.session_state.selected_language) if st.session_state.selected_language != "en" else response
                    st.markdown(translated)
        
        st.session_state.messages.append({"role": "assistant", "content": response})

# ==================== MEDICATIONS PAGE ====================
elif st.session_state.current_page == "medications":
    st.title("💊 Medication Tracker")
    with st.expander("➕ Add New Medication", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            med_name = st.text_input("Medication Name")
        with col2:
            dosage = st.text_input("Dosage", placeholder="e.g., 500mg twice daily")
        with col3:
            reminder_time = st.time_input("Reminder Time")
        if st.button("💾 Add Medication"):
            if med_name and dosage:
                add_medication_to_db(
                    user_id, 
                    med_name, 
                    dosage, 
                    str(reminder_time),
                    st.session_state.user_email
                )
                add_reminder_to_db(user_id, med_name, dosage, str(reminder_time))
                st.success(f"✅ Added {med_name} at {reminder_time} (Reminder email sent!)")
                st.rerun()
    
    st.subheader("📋 Your Medications")
    user_meds = get_user_medications(user_id)
    if user_meds:
        for med in user_meds:
            col1, col2, col3 = st.columns([3, 2, 1])
            col1.markdown(f"**{med['medicine_name']}**")
            col2.markdown(f"{med['dosage']}")
            col3.markdown(f"⏰ {med['reminder_time']}")
            st.divider()
    else:
        st.info("No medications yet. Add one above.")

# ==================== PROFILE PAGE ====================
elif st.session_state.current_page == "profile":
    st.title("📋 Your Health Profile")
    with st.form("update_profile"):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input("Age", value=profile.get("age", 30))
            blood_options = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "Don't know"]
            current_blood = profile.get("blood_type", "Don't know")
            if current_blood in blood_options:
                blood_index = blood_options.index(current_blood)
            else:
                blood_index = 8
            blood_type = st.selectbox("Blood Type", blood_options, index=blood_index)
            height = st.number_input("Height (cm)", value=profile.get("height", 170))
        with col2:
            weight = st.number_input("Weight (kg)", value=profile.get("weight", 70))
            bmi = calculate_bmi(height, weight)
            st.info(f"📊 BMI: {bmi}")
            conditions = st.text_area("Medical Conditions", value=profile.get("conditions", ""))
            allergies = st.text_area("Allergies", value=profile.get("allergies", ""))
            family_history = st.text_area("Family Medical History", value=profile.get("family_history", ""))
            medications_list = st.text_area("Current Medications", value=profile.get("medications_list", ""))
        if st.form_submit_button("Update"):
            updated = {
                "age": age, 
                "blood_type": blood_type, 
                "height": height, 
                "weight": weight, 
                "bmi": bmi,
                "conditions": conditions,
                "allergies": allergies,
                "family_history": family_history,
                "medications_list": medications_list
            }
            save_profile(user_id, updated)
            st.session_state.user_profile = updated
            st.success("Updated!")

# ==================== SEARCH PAGE ====================
elif st.session_state.current_page == "search":
    st.title("🔍 Search Medical Databases")
    search_query = st.text_input("Enter disease or condition to search")
    if search_query:
        encoded = quote(search_query)
        st.markdown(f"🏥 [NHS inform](https://www.nhsinform.scot/search?search_api_fulltext={encoded})")
        st.markdown(f"📚 [MalaCards](https://www.malacards.org/search/results?search_term={encoded})")
        st.markdown(f"📄 [PubMed Central](https://www.ncbi.nlm.nih.gov/pmc/?term={encoded})")
        st.markdown(f"🔬 [MedlinePlus](https://medlineplus.gov/search?query={encoded})")

# ==================== EMERGENCY PAGE ====================
else:
    st.title("🚨 EMERGENCY")
    st.error(f"## CALL {emergency['ambulance']} NOW")
    if st.button(f"🔴 DIAL {emergency['ambulance']}"):
        st.markdown(f"[Click to call {emergency['ambulance']}](tel:{emergency['ambulance']})")

# ==================== DASHBOARD MISSED DOSES ====================
if st.session_state.current_page == "chat" and st.session_state.logged_in:
    missed = get_missed_doses(user_id)
    if missed:
        with st.expander("⚠️ Missed Doses Today", expanded=False):
            for med in missed:
                st.markdown(f"- **{med['medicine_name']}** ({med['dosage']}) at {med['reminder_time']}")

st.markdown('</div>', unsafe_allow_html=True)
st.markdown("---")
st.caption("⚕️ DOCAI | Powered by OpenRouter + Supabase | Always consult your doctor")