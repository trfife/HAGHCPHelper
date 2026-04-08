"""Constants for the GitHub Copilot Conversation integration."""

DOMAIN = "ghcp_conversation"

CONF_BACKEND = "backend"
CONF_GITHUB_TOKEN = "github_token"
CONF_AZURE_ENDPOINT = "azure_endpoint"
CONF_AZURE_API_KEY = "azure_api_key"
CONF_MODEL = "model"
CONF_PROMPT = "prompt"
CONF_TEMPERATURE = "temperature"
CONF_MAX_TOKENS = "max_tokens"
CONF_LLM_HASS_API = "llm_hass_api"

BACKEND_GITHUB = "github_models"
BACKEND_AZURE = "azure_ai"

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_API_VERSION = "2026-03-10"

DEFAULT_MODEL = "openai/gpt-4.1-mini"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096

RECOMMENDED_MODELS = [
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
    "openai/gpt-4o",
    "openai/gpt-5",
    "openai/gpt-5-mini",
    "meta/llama-4-scout",
    "meta/llama-4-maverick",
    "mistral/mistral-large",
    "deepseek/deepseek-r1",
    "xai/grok-3",
    "xai/grok-3-mini",
]

DEFAULT_PROMPT = (
    "You are a helpful smart home assistant for Home Assistant. "
    "You can control devices, query entity states, trigger automations, "
    "and help the user manage their home. "
    "Be concise — keep responses short and natural, especially for voice. "
    "When you control a device, briefly confirm what you did. "
    "When reporting sensor values, include units. "
    "If a request is ambiguous, ask for clarification."
)

CONF_SUBENTRY_TITLE = "title"
SUBENTRY_TYPE_CONVERSATION = "conversation"
