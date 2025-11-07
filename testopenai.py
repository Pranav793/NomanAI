import os
from openai import OpenAI

api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not set in environment variables")

client = OpenAI(api_key=api_key)

try:
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": "Make an RSA key pair and give me the public and private key pair."}
        ],
        max_tokens=512,
        temperature=0.7,
    )
    print(response.choices[0].message.content.strip())
except Exception as e:
    print(f"Error occurred: {e}")
