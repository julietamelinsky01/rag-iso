"""Configuración del prototipo con IA local y Supabase."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
OLLAMA_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "embeddinggemma:latest"
EMBEDDING_DIM = 768
CHAT_MODEL = "qwen3:4b"
TOP_K = 6
