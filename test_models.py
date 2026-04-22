import os
from dotenv import load_dotenv
import requests

load_dotenv()
key = os.getenv("OPENROUTER_API_KEY")

def test():
    print(f"Using Key: {key[:10]}...")
    # Test Chat Model
    res = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "nvidia/nemotron-3-super-120b-a12b:free",
            "messages": [{"role": "user", "content": "Hi"}]
        }
    )
    print("Chat Test:", res.status_code, res.text[:100])

test()