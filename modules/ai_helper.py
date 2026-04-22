import os
import requests
from dotenv import load_dotenv

load_dotenv()

# THE 2 MODELS YOU MUST USE
MODEL_CHAT = "nvidia/nemotron-3-super-120b-a12b:free"
MODEL_EMBED = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def ask_ai(prompt):
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": MODEL_CHAT, 
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 150  # Limits the length to make it faster
            },
            timeout=20
        )
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"AI Error: {e}"

def get_embedding(text):
    """Specific Embedding function"""
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": MODEL_EMBED, "input": text},
            timeout=20
        )
        return response.json()["data"][0]["embedding"]
    except:
        return []

def generate_next_question(history, q_num):
    # This helps the app move through onboarding questions 1-4
    context = str(history)
    prompt = f"User onboarding history: {context}. Ask question #{q_num} as a career mentor."
    return ask_ai(prompt)

def generate_final_summary(history):
    # This creates the final profile summary after 4 questions
    prompt = f"Based on these 4 answers, write a professional goal summary: {history}"
    return ask_ai(prompt)

def get_mentor_reply(profile, history, user_msg):
    # This handles the main mentor chat
    prompt = f"Profile: {profile}. History: {history}. User says: {user_msg}. Reply as a mentor."
    return ask_ai(prompt)