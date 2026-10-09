import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()  # Loads OPENAI_API_KEY and OPENAI_BASE_URL from .env


def pick_llm(Level: str):
    """Function to pick the appropriate LLM based on the provided level.

    Args:
        Level (str): 'low', 'medium', or 'high'.

    Returns:
        ChatOpenAI: Configured LangChain ChatOpenAI instance.
    """
    level = Level.lower()

    if level == "low":
        # Lightweight and fast (Free tier)
        llm = ChatOpenAI(model="gemini-3.5-flash-lite", temperature=0)
    elif level == "medium":
        # Standard balanced model (Free tier)
        llm = ChatOpenAI(model="gemini-3.8-flash", temperature=0)
    elif level == "high":
        # Highly capable flagship reasoning model (Free tier)
        llm = ChatOpenAI(model="gemma-4-31b-it", temperature=0)
    else:
        raise ValueError(
            "Invalid level provided. Please choose from 'low', 'medium', or 'high'."
        )

    return llm


