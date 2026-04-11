"""Constants for the GitHub Copilot Conversation integration."""

DOMAIN = "ghcp_conversation"

CONF_BACKEND = "backend"
CONF_GITHUB_TOKEN = "github_token"
CONF_AZURE_ENDPOINT = "azure_endpoint"
CONF_AZURE_API_KEY = "azure_api_key"
CONF_MODEL = "model"
CONF_EXPERT_MODEL = "expert_model"
CONF_PROMPT = "prompt"
CONF_TEMPERATURE = "temperature"
CONF_MAX_TOKENS = "max_tokens"
CONF_LLM_HASS_API = "llm_hass_api"
CONF_AUTH_METHOD = "auth_method"

AUTH_METHOD_BROWSER = "browser"
AUTH_METHOD_PAT = "pat"

BACKEND_GITHUB = "github_models"
BACKEND_AZURE = "azure_ai"
BACKEND_COPILOT_CLI = "copilot_cli"
BACKEND_HYBRID = "hybrid"

# ACP (Agent Client Protocol) settings for Copilot CLI add-on
CONF_ACP_HOST = "acp_host"
CONF_ACP_PORT = "acp_port"
ACP_DEFAULT_PORT = 3000
ADDON_SLUG = "copilot_cli"

# Azure AI Foundry router settings (used by hybrid backend)
CONF_AZURE_ROUTER_ENDPOINT = "azure_router_endpoint"
CONF_AZURE_ROUTER_KEY = "azure_router_key"
CONF_AZURE_ROUTER_MODEL = "azure_router_model"
DEFAULT_AZURE_ROUTER_MODEL = "gpt-4.1-mini"

# Register an OAuth App at https://github.com/settings/applications/new
# Enable "Device Flow" on the app settings page.  Paste the Client ID here.
GITHUB_OAUTH_CLIENT_ID = "Ov23li4rTBw9XPm1olwk"

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_CATALOG_URL = "https://models.github.ai/catalog/models"
GITHUB_API_VERSION = "2026-03-10"

DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096

# Fallback models when catalog API is unavailable
FALLBACK_MODELS = [
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-5.4-mini",
    "claude-haiku-4.5",
    "gpt-5.4",
    "claude-sonnet-4.6",
    "claude-opus-4.6",
]

DEFAULT_PROMPT = (
    "You are a helpful smart home assistant for Home Assistant. "
    "You can control devices, query entity states, trigger automations, "
    "and help the user manage their home.\n\n"
    "## Voice Response Rules\n"
    "Your responses are spoken aloud via text-to-speech. Follow these rules:\n"
    "- Keep your spoken response to 1–2 sentences MAX. Be brief and natural.\n"
    "- Use natural vocal cues where appropriate: "
    '"Hmm...", "Haha", "*sighs*", "Oh!", "Alright!", "Ugh", "Wow" — '
    "these add personality when spoken by the TTS engine.\n"
    "- When you control a device, briefly confirm what you did.\n"
    "- When reporting sensor values, include units.\n"
    "- If a request is ambiguous, ask for clarification.\n\n"
    "## Detailed Responses\n"
    "If your answer needs more detail than 1–2 sentences (explanations, lists, "
    "step-by-step instructions, analysis), structure your response like this:\n"
    "1. Start with a short spoken summary (1–2 sentences).\n"
    "2. Then add `[[DETAIL]]` on its own line.\n"
    "3. After the marker, include the full detailed response.\n\n"
    "The short part will be spoken aloud. The full response (including detail) "
    "will be sent via email. If the answer is simple, skip the marker entirely."
)

# Separator used to split spoken vs detailed content in responses
VOICE_DETAIL_SEPARATOR = "[[DETAIL]]"

# Orchestrator / expert escalation
EXPERT_TOOL_NAME = "ask_expert"
KNOWLEDGE_TOOL_NAME = "search_knowledge"
KNOWLEDGE_STORE_KEY = "ghcp_conversation.knowledge"
KNOWLEDGE_MAX_ENTRIES = 200

ORCHESTRATOR_PROMPT_SUFFIX = (
    "\n\n## Orchestrator Mode\n"
    "You have two special tools: `search_knowledge` and `ask_expert`.\n"
    "- For simple tasks (device control, status queries, quick answers), "
    "handle them yourself — do NOT use these tools.\n"
    "- For complex questions that require deep reasoning, planning, analysis, "
    "or when the user says 'think harder', 'use expert', or 'be thorough':\n"
    "  1. FIRST call `search_knowledge` to check if a similar question was "
    "answered before.\n"
    "  2. If a relevant match is found, use that answer directly.\n"
    "  3. Only call `ask_expert` if no relevant knowledge was found.\n"
    "- Present all answers naturally without mentioning tools or escalation."
)

# Email notification settings
CONF_EMAIL_NOTIFY_SERVICE = "email_notify_service"
CONF_EMAIL_MODE = "email_mode"
CONF_EMAIL_THRESHOLD = "email_threshold"

EMAIL_MODE_OFF = "off"
EMAIL_MODE_ALWAYS = "always"
EMAIL_MODE_LONG_ONLY = "long_only"

DEFAULT_EMAIL_MODE = EMAIL_MODE_OFF
DEFAULT_EMAIL_THRESHOLD = 500
MAX_EMAIL_THINKING_CHARS = 50000

CONF_SUBENTRY_TITLE = "title"
SUBENTRY_TYPE_CONVERSATION = "conversation"
