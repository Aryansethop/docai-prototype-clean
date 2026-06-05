import streamlit as st
import requests
import hashlib
import re
import html
import unicodedata
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from supabase import create_client

# ==================== PAGE CONFIG ====================
st.set_page_config(page_title="DOCAI - Medical Intelligence", page_icon="⚕️", layout="wide")

# ==================== CSS ====================
st.markdown("""
<style>
.stChatMessage { padding: 10px; }
div[data-testid="stChatMessageUser"] { background-color: #e8f0fe; border-radius: 15px; }
div[data-testid="stChatMessageAssistant"] { background-color: #f0f0f0; border-radius: 15px; }
.stButton > button { background-color: #0b835c; color: white; border-radius: 20px; }
.stButton > button:hover { background-color: #0a6e4e; }
</style>
""", unsafe_allow_html=True)

# ==================== CONFIG ====================
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
DOCTOR_PASSWORD = st.secrets.get("DOCTOR_PASSWORD", "docai2026")

# ==================== SUPABASE ====================
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def create_user(username, email, phone, password):
    supabase = get_supabase()
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
    supabase = get_supabase()
    try:
        result = supabase.table("users").select("*").eq("email", email).execute()
        user = result.data[0] if result.data else None
        if user and user["password"] == hash_password(password):
            return user
    except:
        pass
    return None

def get_profile(user_id):
    supabase = get_supabase()
    try:
        result = supabase.table("profiles").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None
    except:
        return None

def save_profile(user_id, profile_data):
    supabase = get_supabase()
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
    supabase = get_supabase()
    try:
        supabase.table("feedback").insert({
            "user_id": user_id, "response_id": str(response_id),
            "rating": int(rating), "comment": comment[:200]
        }).execute()
        return True
    except:
        return False

def submit_feedback(user_id, username, feedback_text):
    supabase = get_supabase()
    try:
        supabase.table("feedback").insert({
            "user_id": user_id, "username": username, "feedback_text": feedback_text[:1000]
        }).execute()
        return True
    except:
        return False

def log_audit(user_id, user_input, ai_output, emergency=False, sources=None):
    supabase = get_supabase()
    try:
        data = {
            "user_id": user_id,
            "user_input": user_input[:500],
            "ai_output": ai_output[:1000],
            "emergency_triggered": emergency,
            "created_at": datetime.now().isoformat()
        }
        if sources:
            data["sources"] = sources
        supabase.table("audit_logs").insert(data).execute()
    except:
        pass

# ==================== PubMed Search (Full Abstracts) ====================
_last_pubmed_request = 0

def search_pubmed(query):
    """Search PubMed and return FULL ABSTRACTS of recent papers"""
    global _last_pubmed_request
    
    # Rate limit: at least 1 second between requests
    elapsed = time.time() - _last_pubmed_request
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    
    _last_pubmed_request = time.time()
    
    try:
        encoded_query = requests.utils.quote(query)
        
        # Step 1: Search for paper IDs
        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={encoded_query}&retmax=3&sort=relevance&format=json"
        search_response = requests.get(search_url, timeout=15)
        
        if search_response.status_code != 200:
            return [], ""
        
        data = search_response.json()
        paper_ids = data.get('esearchresult', {}).get('idlist', [])
        
        if not paper_ids:
            return [], ""
        
        # Step 2: Fetch FULL abstracts (not just titles)
        ids_string = ",".join(paper_ids)
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={ids_string}&retmode=xml"
        fetch_response = requests.get(fetch_url, timeout=15)
        
        if fetch_response.status_code != 200:
            return [], ""
        
        # Step 3: Parse XML to extract abstracts
        root = ET.fromstring(fetch_response.content)
        
        papers = []
        sources = []
        
        for article in root.findall('.//PubmedArticle'):
            # Get title
            title_elem = article.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else "No title"
            
            # Get abstract text
            abstract_text = []
            abstract_elem = article.find('.//Abstract')
            if abstract_elem is not None:
                for text_elem in abstract_elem.findall('.//AbstractText'):
                    if text_elem.text:
                        abstract_text.append(text_elem.text)
            
            abstract = " ".join(abstract_text) if abstract_text else "Abstract not available"
            
            # Get publication date
            pubdate_elem = article.find('.//PubDate/Year')
            pubdate = pubdate_elem.text if pubdate_elem is not None else "Date unknown"
            
            # Truncate abstract to reasonable length (1500 chars)
            abstract_preview = abstract[:1500] + "..." if len(abstract) > 1500 else abstract
            
            paper_info = f"**{title}** ({pubdate})\n{abstract_preview}\n"
            papers.append(paper_info)
            sources.append(f"PubMed: {title}")
        
        if papers:
            return sources, "**Recent Medical Research (PubMed):**\n\n" + "\n---\n".join(papers) + "\n"
        return [], ""
        
    except Exception as e:
        print(f"PubMed search error: {e}")
        return [], ""

# ==================== Local Medical Knowledge ====================
def search_local_knowledge(query):
    query_lower = query.lower()
    knowledge = {
        "diabetic neuropathy": "Diabetic neuropathy: First-line treatment is Gabapentin 300mg at night, increasing to 1800mg daily. Alternative: Pregabalin 50mg three times daily. Essential: Strict blood sugar control (HbA1c <7%), daily foot inspection.",
        "type 2 diabetes": "Type 2 Diabetes: First-line medication is Metformin 500mg twice daily, increase to 1000mg twice daily. Second-line: Glimepiride 1-4mg daily, Empagliflozin 10-25mg daily.",
        "dust allergy": "Dust Allergy: Antihistamines: Cetirizine 10mg daily or Loratadine 10mg daily. Prevention: HEPA filters, allergen-proof covers, wash bedding at 60°C.",
        "gastric reflux": "Gastric Reflux: Ginger tea, fennel seeds, small frequent meals. Avoid baking soda, caffeine, spicy foods.",
        "hypertension": "Hypertension: Lisinopril 10mg daily or Amlodipine 5mg daily. Lifestyle: Low sodium diet, exercise 150 min/week."
    }
    for condition, answer in knowledge.items():
        if condition in query_lower:
            return answer
    return ""

# ==================== AI ====================
EMERGENCY_KEYWORDS = [
    "chest pain", "heart attack", "can't breathe", "unconscious",
    "severe bleeding", "seizure", "stroke", "choking", "overdose"
]

EMERGENCY_NUMBERS = {"IN": "108", "US": "911", "default": "112"}

def get_emergency_number():
    try:
        resp = requests.get('https://ip-api.com/json/', timeout=2)
        if resp.status_code == 200:
            country = resp.json().get('countryCode', 'IN')
            return EMERGENCY_NUMBERS.get(country, EMERGENCY_NUMBERS["default"])
    except:
        pass
    return EMERGENCY_NUMBERS["default"]

def expand_medical_terms(text):
    """Convert patient slang to medical terms using comprehensive mapping"""
    result = text.lower()
    
    mappings = {
        # Diabetes (15+ variations)
        "sugar problem": "diabetes",
        "sugar": "diabetes",
        "blood sugar": "diabetes",
        "sugar level": "diabetes",
        "high sugar": "diabetes",
        "glucose": "diabetes",
        "high glucose": "diabetes",
        "sugar ki bimari": "diabetes",
        "sweet urine": "diabetes",
        "diabetes": "diabetes",
        "diabetic": "diabetes",
        "type 2": "diabetes",
        "type two": "diabetes",
        "blood glucose": "diabetes",
        
        # Neuropathy / Foot Numbness (15+ variations)
        "feets": "feet",
        "foots": "feet",
        "numb": "neuropathy",
        "numbness": "neuropathy",
        "tingling": "neuropathy",
        "burning feet": "neuropathy",
        "pins and needles": "neuropathy",
        "can't feel my feet": "neuropathy",
        "loss of feeling": "neuropathy",
        "foot pain": "neuropathy",
        "feet pain": "neuropathy",
        "toe numbness": "neuropathy",
        "leg numbness": "neuropathy",
        "walking problem": "neuropathy",
        
        # Hypertension / Blood Pressure (8+ variations)
        "high bp": "hypertension",
        "blood pressure": "hypertension",
        "bp": "blood pressure",
        "pressure high": "hypertension",
        "bp problem": "hypertension",
        "tension": "hypertension",
        "high blood pressure": "hypertension",
        "bp high": "hypertension",
        
        # Asthma / Breathing (10+ variations)
        "breathing problem": "asthma",
        "can't breathe": "asthma emergency",
        "wheezing": "asthma",
        "shortness of breath": "asthma",
        "chest tightness": "asthma",
        "difficulty breathing": "asthma",
        "out of breath": "asthma",
        "breathless": "asthma",
        "asthma attack": "asthma emergency",
        
        # Gastric / Stomach (12+ variations)
        "stomach issue": "gastric",
        "gas problem": "gastric",
        "acidity": "gastric",
        "heartburn": "gastric",
        "indigestion": "gastric",
        "bloating": "gastric",
        "gerd": "gastric",
        "acid reflux": "gastric",
        "stomach pain": "gastric",
        "abdomen pain": "gastric",
        "digestion problem": "gastric",
        
        # General symptoms (10+ variations)
        "feeling sick": "nausea",
        "vomiting": "nausea",
        "headache": "cephalalgia",
        "fever": "pyrexia",
        "cold": "upper respiratory infection",
        "cough": "cough",
        "sore throat": "pharyngitis",
        "runny nose": "rhinitis",
        "body pain": "myalgia",
        "weakness": "asthenia"
    }
    
    for slang, medical in mappings.items():
        if slang in result:
            result = result.replace(slang, medical)
    
    return result

def check_emergency(text):
    for kw in EMERGENCY_KEYWORDS:
        if kw in text.lower():
            return True, f"🚨 EMERGENCY - Call {get_emergency_number()} immediately"
    return False, None

def get_ai_response(query, profile):
    original_query = query
    query = expand_medical_terms(query)
    
    is_emerg, emg_msg = check_emergency(query)
    if is_emerg:
        log_audit(profile.get('user_id', 0) if profile else 0, original_query, emg_msg, emergency=True)
        return emg_msg
    
    local_info = search_local_knowledge(query)
    pubmed_sources, pubmed_info = search_pubmed(original_query)
    
    all_sources = []
    if local_info:
        all_sources.append("Local Knowledge Base")
    if pubmed_sources:
        all_sources.extend(pubmed_sources)
    
    profile_text = ""
    if profile:
        conditions = profile.get('conditions', 'None')
        allergies = profile.get('allergies', 'None')
        family = profile.get('family_history', 'None')
        profile_text = f"PATIENT PROFILE:\n- Conditions: {conditions}\n- Allergies: {allergies}\n- Family History: {family}\n"
    
    context_section = ""
    if local_info or pubmed_info:
        context_section = "**MEDICAL SOURCES:**\n"
        if local_info:
            context_section += f"📚 Local Medical Knowledge:\n{local_info}\n\n"
        if pubmed_info:
            context_section += f"📖 PubMed Research (Full Abstracts):\n{pubmed_info}\n"
        context_section += "-" * 50 + "\n"
    
    prompt = f"""You are a medical AI assistant. Use the information below to answer.

{context_section}
{profile_text}

QUESTION: {query}

INSTRUCTIONS:
1. Give specific medicine names and dosages
2. Consider the patient's conditions and allergies
3. Base your answer on the medical sources provided above
4. End with: "⚠️ Always consult your doctor."

ANSWER:"""
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 800
            },
            timeout=30
        )
        if response.status_code == 200:
            ai_response = response.json()["choices"][0]["message"]["content"]
            log_audit(profile.get('user_id', 0) if profile else 0, original_query, ai_response, sources=", ".join(all_sources) if all_sources else None)
            return ai_response
        return "I'm having trouble. Please consult a doctor."
    except Exception as e:
        return f"Connection error. Please try again."

def calculate_bmi(h, w):
    if h and w and h > 0:
        bmi = w / ((h/100) ** 2)
        if bmi < 18.5: return f"{bmi:.1f} (Underweight)"
        if bmi < 25: return f"{bmi:.1f} (Normal)"
        if bmi < 30: return f"{bmi:.1f} (Overweight)"
        return f"{bmi:.1f} (Obese)"
    return "Not calculated"

# ==================== SESSION ====================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.user_id = None
    st.session_state.user_profile = None
    st.session_state.messages = []
    st.session_state.current_page = "chat"
    st.session_state.is_doctor = False

# ==================== LOGIN ====================
if not st.session_state.logged_in:
    st.title("⚕️ DOCAI")
    st.markdown("### Medical Intelligence for Every Human")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("✅ Medicine information\n✅ Symptoms & treatments\n✅ Emergency numbers")
    with col2:
        st.markdown("✅ BMI calculator\n✅ Voice input\n✅ Medical search")
    
    tab1, tab2, tab3 = st.tabs(["🔐 User Login", "📝 Sign Up", "👨‍⚕️ Doctor Login"])
    
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
                    st.session_state.user_profile = get_profile(user["id"]) or {}
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
    
    with tab3:
        with st.form("doctor_login"):
            doctor_pass = st.text_input("Doctor Password", type="password")
            if st.form_submit_button("Login as Doctor"):
                if doctor_pass == DOCTOR_PASSWORD:
                    st.session_state.logged_in = True
                    st.session_state.username = "Doctor"
                    st.session_state.user_id = 0
                    st.session_state.is_doctor = True
                    st.rerun()
                else:
                    st.error("Invalid password")
    st.stop()

# ==================== PROFILE SETUP ====================
if not st.session_state.user_profile and not st.session_state.is_doctor:
    st.title("📋 Complete Your Medical Profile")
    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input("Age", 0, 120, 30)
            height = st.number_input("Height (cm)", 50, 250, 170)
        with col2:
            weight = st.number_input("Weight (kg)", 10, 300, 70)
            st.info(f"BMI: {calculate_bmi(height, weight)}")
        
        conditions = st.text_area("Medical Conditions", placeholder="e.g., diabetes, hypertension")
        allergies = st.text_area("Allergies", placeholder="e.g., penicillin")
        family_history = st.text_area("Family Medical History", placeholder="e.g., diabetes, heart disease")
        
        if st.form_submit_button("Save Profile"):
            save_profile(st.session_state.user_id, {
                "age": age, "height": height, "weight": weight,
                "conditions": conditions, "allergies": allergies,
                "family_history": family_history
            })
            st.session_state.user_profile = {
                "age": age, "height": height, "weight": weight,
                "conditions": conditions, "allergies": allergies,
                "family_history": family_history
            }
            st.success("Profile saved!")
            st.rerun()
    st.stop()

# ==================== DOCTOR DASHBOARD ====================
if st.session_state.is_doctor:
    st.title("👨‍⚕️ Doctor Review Dashboard")
    supabase = get_supabase()
    logs = supabase.table("audit_logs").select("*").order("created_at", desc=True).limit(50).execute()
    
    if logs.data:
        for log in logs.data:
            with st.expander(f"📋 {log['created_at'][:16]} - {log['user_input'][:60]}..."):
                st.markdown(f"**Question:** {log['user_input']}")
                st.markdown(f"**AI Response:** {log['ai_output']}")
                if log.get('sources'):
                    st.caption(f"Sources: {log['sources']}")
                st.caption(f"Emergency: {log.get('emergency_triggered', False)}")
    else:
        st.info("No user questions yet.")
    
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()
    st.stop()

# ==================== MAIN APP ====================
emergency_num = get_emergency_number()

with st.sidebar:
    st.title(f"👋 {st.session_state.username}")
    st.markdown(f"🚑 **Emergency:** {emergency_num}")
    
    if st.button("💬 Chat", use_container_width=True):
        st.session_state.current_page = "chat"
    if st.button("📋 Profile", use_container_width=True):
        st.session_state.current_page = "profile"
    if st.button("🚨 Emergency", use_container_width=True):
        st.session_state.current_page = "emergency"
    
    st.markdown("---")
    if st.session_state.user_profile:
        p = st.session_state.user_profile
        if p.get('conditions'):
            st.caption(f"🩺 {p['conditions'][:50]}")
        if p.get('allergies'):
            st.caption(f"⚠️ {p['allergies'][:50]}")
    
    st.markdown("---")
    feedback = st.text_area("💬 Send Feedback", height=80)
    if st.button("Submit Feedback") and feedback.strip():
        submit_feedback(st.session_state.user_id, st.session_state.username, feedback)
        st.success("Thank you!")
    
    if st.button("🚪 Logout"):
        st.session_state.logged_in = False
        st.session_state.messages = []
        st.rerun()

# ==================== CHAT PAGE ====================
if st.session_state.current_page == "chat":
    st.title("🤖 Medical AI Assistant")
    st.caption(f"Emergency: {emergency_num}")
    
    if st.session_state.user_profile and st.session_state.user_profile.get('conditions'):
        st.info(f"🩺 Using your profile: {st.session_state.user_profile['conditions'][:80]}")
    
    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("👍 Helpful", key=f"up_{i}"):
                        save_feedback(st.session_state.user_id, f"msg_{i}", 1)
                        st.toast("Thanks!")
                with c2:
                    if st.button("👎 Not Helpful", key=f"down_{i}"):
                        save_feedback(st.session_state.user_id, f"msg_{i}", -1)
                        st.toast("Recorded")
    
    user_input = st.chat_input("Ask about any disease, medicine, or symptom...")
    
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        
        with st.chat_message("assistant"):
            with st.spinner("Searching PubMed and analyzing your question..."):
                response = get_ai_response(user_input, st.session_state.user_profile)
                st.markdown(response)
        
        st.session_state.messages.append({"role": "assistant", "content": response})

# ==================== PROFILE PAGE ====================
elif st.session_state.current_page == "profile":
    st.title("📋 Your Health Profile")
    p = st.session_state.user_profile
    if p:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Age", p.get('age', 'N/A'))
            st.metric("Height", f"{p.get('height', 'N/A')} cm")
        with col2:
            st.metric("Weight", f"{p.get('weight', 'N/A')} kg")
            st.metric("BMI", calculate_bmi(p.get('height', 170), p.get('weight', 70)))
        
        st.markdown("### Medical Information")
        st.markdown(f"**Conditions:** {p.get('conditions', 'None')}")
        st.markdown(f"**Allergies:** {p.get('allergies', 'None')}")
        st.markdown(f"**Family History:** {p.get('family_history', 'None')}")
    else:
        st.info("No profile data found.")

# ==================== EMERGENCY PAGE ====================
else:
    st.title("🚨 EMERGENCY")
    st.error(f"CALL {emergency_num} NOW")
    if st.button(f"📞 Call {emergency_num}"):
        st.markdown(f"[Click to call {emergency_num}](tel:{emergency_num})")

st.markdown("---")
st.caption("⚕️ DOCAI | Always consult your doctor for medical advice")