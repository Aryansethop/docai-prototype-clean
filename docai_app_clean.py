import streamlit as st
import requests
import json
import hashlib
import os
import re
import time
from datetime import datetime
from urllib.parse import quote
import html
import unicodedata
from supabase import create_client

st.set_page_config(page_title="DOCAI", page_icon="⚕️", layout="wide")

# Simple CSS
st.markdown("""
<style>
.stChatMessage { padding: 10px; }
div[data-testid="stChatMessageUser"] { background-color: #e8f0fe; border-radius: 15px; }
div[data-testid="stChatMessageAssistant"] { background-color: #f0f0f0; border-radius: 15px; }
.stButton > button { background-color: #0b835c; color: white; }
</style>
""", unsafe_allow_html=True)

# Emergency numbers
EMERGENCY_NUMBERS = {
    "IN": {"ambulance": "108", "name": "India"},
    "US": {"ambulance": "911", "name": "USA"},
    "default": {"ambulance": "112", "name": "International"}
}

def detect_country():
    try:
        response = requests.get('https://ip-api.com/json/', timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                return data.get('countryCode', 'IN')
    except:
        pass
    return "IN"

country_code = detect_country()
emergency = EMERGENCY_NUMBERS.get(country_code, EMERGENCY_NUMBERS["default"])

# Supabase - CLEAN VERSION
def get_supabase_client():
    try:
        SUPABASE_URL = st.secrets["SUPABASE_URL"]
        SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.error(f"Supabase error: {e}")
        st.stop()

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def create_user(username, email, phone, password):
    supabase = get_supabase_client()
    try:
        result = supabase.table("users").insert({
            "username": username, "email": email, "phone": phone,
            "password": hash_password(password)
        }).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        st.error(f"Error: {e}")
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

def get_profile(user_id):
    supabase = get_supabase_client()
    try:
        result = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None
    except:
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
    except:
        return None

def save_feedback(user_id, response_id, rating, comment=""):
    supabase = get_supabase_client()
    try:
        supabase.table("feedback").insert({
            "user_id": user_id, "response_id": response_id,
            "rating": rating, "comment": comment[:200]
        }).execute()
        return True
    except:
        return False

def submit_user_feedback(user_id, username, feedback_text, page_url=""):
    supabase = get_supabase_client()
    try:
        supabase.table("feedback").insert({
            "user_id": user_id, "username": username,
            "feedback_text": feedback_text[:1000], "page_url": page_url
        }).execute()
        return True
    except:
        return False

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

# OpenRouter
try:
    OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
except:
    st.error("OpenRouter API key missing")
    st.stop()

EMERGENCY_KEYWORDS = ["chest pain", "heart attack", "can't breathe", "unconscious", "severe bleeding", "seizure", "stroke", "choking", "overdose"]

def check_emergency(user_input):
    user_lower = user_input.lower()
    for kw in EMERGENCY_KEYWORDS:
        if kw in user_lower:
            return True, f"EMERGENCY - Call {emergency['ambulance']} immediately"
    return False, None

def get_ai_response(user_query, user_profile, chat_history, username, user_id):
    cleaned_query = user_query.strip()
    is_emergency, emg_msg = check_emergency(cleaned_query)
    if is_emergency:
        return emg_msg
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "openai/gpt-3.5-turbo",
                "messages": [{"role": "user", "content": f"Medical question: {cleaned_query}. Provide safe advice. Always say consult doctor."}],
                "temperature": 0.3,
                "max_tokens": 500
            },
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        else:
            return "I'm having trouble right now. Please try again or consult a doctor."
    except:
        return "Unable to get response. Please check your internet connection."

# Session state
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_profile" not in st.session_state:
    st.session_state.user_profile = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_page" not in st.session_state:
    st.session_state.current_page = "chat"

# Login
if not st.session_state.logged_in:
    st.title("DOCAI")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])
    
    with tab1:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                user = verify_login(email, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.username = user["username"]
                    st.session_state.user_id = user["id"]
                    profile = get_profile(user["id"])
                    st.session_state.user_profile = profile if profile else {}
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    
    with tab2:
        with st.form("signup_form"):
            username = st.text_input("Username")
            email = st.text_input("Email")
            phone = st.text_input("Phone")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm", type="password")
            if st.form_submit_button("Sign Up"):
                if password != confirm:
                    st.error("Passwords don't match")
                elif len(password) < 4:
                    st.error("Password too short")
                else:
                    user = create_user(username, email, phone, password)
                    if user:
                        st.success("Account created! Please login.")
                    else:
                        st.error("Username or email exists")
    st.stop()

# Profile setup
if not st.session_state.user_profile:
    st.title("Complete Your Profile")
    with st.form("profile_form"):
        age = st.number_input("Age", min_value=0, max_value=120, value=30)
        height = st.number_input("Height (cm)", value=170)
        weight = st.number_input("Weight (kg)", value=70)
        conditions = st.text_area("Medical Conditions")
        allergies = st.text_area("Allergies")
        if st.form_submit_button("Save"):
            profile_data = {"age": age, "height": height, "weight": weight, "conditions": conditions, "allergies": allergies}
            save_profile(st.session_state.user_id, profile_data)
            st.session_state.user_profile = profile_data
            st.rerun()
    st.stop()

# Main app
with st.sidebar:
    st.title(f"Welcome {st.session_state.username}")
    st.markdown(f"Emergency: {emergency['ambulance']}")
    
    if st.button("Chat"):
        st.session_state.current_page = "chat"
    if st.button("Profile"):
        st.session_state.current_page = "profile"
    if st.button("Emergency"):
        st.session_state.current_page = "emergency"
    
    st.markdown("---")
    st.markdown("### Send Feedback")
    feedback_text = st.text_area("Report a problem", key="feedback_input")
    if st.button("Submit Feedback"):
        if feedback_text.strip():
            submit_user_feedback(st.session_state.user_id, st.session_state.username, feedback_text, st.session_state.current_page)
            st.success("Thank you!")
    
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.messages = []
        st.rerun()

# Chat page
if st.session_state.current_page == "chat":
    st.title("Medical AI Assistant")
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
    
    user_input = st.chat_input("Ask a medical question...")
    
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = get_ai_response(user_input, st.session_state.user_profile, st.session_state.messages, st.session_state.username, st.session_state.user_id)
                st.markdown(response)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("👍", key="helpful"):
                        save_feedback(st.session_state.user_id, "response", 1)
                        st.toast("Thanks!")
                with col2:
                    if st.button("👎", key="not_helpful"):
                        save_feedback(st.session_state.user_id, "response", -1)
                        st.toast("Feedback recorded")
        
        st.session_state.messages.append({"role": "assistant", "content": response})

# Profile page
elif st.session_state.current_page == "profile":
    st.title("Your Profile")
    profile = st.session_state.user_profile
    st.json(profile)

# Emergency page
else:
    st.title("EMERGENCY")
    st.error(f"CALL {emergency['ambulance']} NOW")
