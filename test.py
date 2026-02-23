from google import genai

client = genai.Client(api_key="AIzaSyBaQEJT0ugIYMsnE4c8e8HD8t6IfXQX62E")

response = client.models.generate_content(
    model="gemini-2.0-flash",
    contents="Say hello in one sentence.",
)

print(response.text)