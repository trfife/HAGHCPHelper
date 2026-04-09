---
description: "Use when editing config_flow.py, strings.json, or translations. Covers HA config flow patterns, form validation, and string sync requirements."
applyTo: ["**/config_flow.py", "**/strings.json", "**/translations/en.json"]
---
# Config Flow & UI Strings Rules

## Config Flow Pattern
- Each backend gets its own `async_step_*` method
- `async_step_user` routes to the right step based on `CONF_BACKEND`
- Validate connections BEFORE creating the entry (show errors on retry)
- Use `errors["base"]` for general errors, `errors[FIELD_NAME]` for field-specific

## Azure Validation
- Always pass `model=` to `build_azure_client()` so the deployment URL is correct
- Use `async_validate(model)` to test the connection
- status 401/403 → `invalid_auth`, other 4xx/5xx → `azure_cannot_connect`

## Strings Sync — CRITICAL
- `strings.json` and `translations/en.json` MUST have identical structure
- Every new step needs entries in BOTH files under `config.step.{step_name}`
- Every new error needs entries in BOTH files under `config.error.{error_key}`
- Test by loading the integration in HA — missing strings show raw keys

## Form Schema
- `vol.Required(KEY)` — field must be filled
- `vol.Optional(KEY)` — field can be blank (shows as optional in UI)
- Use `TextSelectorConfig(type=TextSelectorType.PASSWORD)` for secrets
- Use `TextSelectorConfig(type=TextSelectorType.URL)` for endpoints
