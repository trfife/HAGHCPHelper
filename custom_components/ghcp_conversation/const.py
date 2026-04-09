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

# ACP (Agent Client Protocol) settings for Copilot CLI add-on
CONF_ACP_HOST = "acp_host"
CONF_ACP_PORT = "acp_port"
ACP_DEFAULT_PORT = 3000
ADDON_SLUG = "copilot_cli"

# Register an OAuth App at https://github.com/settings/applications/new
# Enable "Device Flow" on the app settings page.  Paste the Client ID here.
GITHUB_OAUTH_CLIENT_ID = "Ov23li4rTBw9XPm1olwk"

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_CATALOG_URL = "https://models.github.ai/catalog/models"
GITHUB_API_VERSION = "2026-03-10"

DEFAULT_MODEL = "openai/gpt-5-nano"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096

# Fallback models when catalog API is unavailable
FALLBACK_MODELS = [
    "openai/gpt-5-nano",
    "openai/gpt-5-mini",
    "openai/gpt-5",
    "openai/gpt-4.1-nano",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1",
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

CONF_SUBENTRY_TITLE = "title"
SUBENTRY_TYPE_CONVERSATION = "conversation"
