import os
from dotenv import load_dotenv

load_dotenv("./.envvar")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
TURBO_ASSISTANT_ID = os.getenv("TURBO_ASSISTANT_ID")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
GEMINI_API_KEY=os.getenv("GEMINI_API_KEY")
PINECONE=os.getenv("PINECONE")
MONGO_URI = os.getenv("MONGO_URI")
