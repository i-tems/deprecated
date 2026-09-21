import os
import json
from dotenv import load_dotenv
from llm_client import get_llm_client

def get_config(book_id, key, default=None):
    with open(f"config/{book_id}.json", "r") as fp:
        book_config = json.loads(fp.read())
        if key in book_config:
            return book_config[key]
        elif default is not None:
            return default
        else:
            raise KeyError(f"Key '{key}' not found in config file.")

def get_output_dir(book_id, type):
    output_dir = os.path.abspath(f"output/{book_id}/{type}")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def get_llm_provider(book_id):
    """Get LLM provider and model from config, defaulting to OpenAI"""
    load_dotenv()
    provider = get_config(book_id, "llm_provider", default="openai")
    model = get_config(book_id, "llm_model", default=None)

    # Set default models if not specified
    if model is None:
        if provider.lower() == "openai":
            model = "gpt-4o-mini"
        elif provider.lower() == "claude":
            model = "claude-3-5-sonnet-20241022"

    client = get_llm_client(provider)
    return client, model
