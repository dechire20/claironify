from google import genai


response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Say hello in one sentence.",
)

print(response.text)
