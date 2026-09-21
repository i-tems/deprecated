import os
from dotenv import load_dotenv
from abc import ABC, abstractmethod

class LLMClient(ABC):
    """Base class for LLM clients"""

    @abstractmethod
    def chat_completion(self, messages, model):
        """Generate a chat completion"""
        pass

class OpenAIClient(LLMClient):
    """OpenAI API client"""

    def __init__(self):
        load_dotenv()
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        self.client = openai

    def chat_completion(self, messages, model="gpt-4o-mini"):
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
        )
        return response.choices[0].message.content

class ClaudeClient(LLMClient):
    """Anthropic Claude API client"""

    def __init__(self):
        load_dotenv()
        from anthropic import Anthropic
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def chat_completion(self, messages, model="claude-3-5-sonnet-20241022"):
        # Claude API uses a different message format
        # Extract system message if present
        system_message = None
        user_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                user_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        # Call Claude API
        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "messages": user_messages
        }

        if system_message:
            kwargs["system"] = system_message

        response = self.client.messages.create(**kwargs)
        return response.content[0].text

def get_llm_client(provider="openai"):
    """Factory function to get the appropriate LLM client

    Args:
        provider: Either "openai" or "claude"

    Returns:
        LLMClient instance
    """
    if provider.lower() == "openai":
        return OpenAIClient()
    elif provider.lower() == "claude":
        return ClaudeClient()
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'claude'")
