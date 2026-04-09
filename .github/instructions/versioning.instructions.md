---
description: "Use when bumping versions, creating releases, updating CHANGELOG, or syncing files between custom_components and copilot-cli."
---
# Version & Release Checklist

## Version Bump — ALL 5 locations

1. `custom_components/ghcp_conversation/manifest.json` → `"version": "X.Y.Z"`
2. `custom_components/ghcp_conversation/acp_client.py` → `CLIENT_VERSION = "X.Y.Z"`
3. `copilot-cli/config.yaml` → `version: "X.Y.Z"`
4. Run sync: `Copy-Item -Path "custom_components\ghcp_conversation\*" -Destination "copilot-cli\ghcp_conversation\" -Recurse -Force`
5. Verify #4 updated both `copilot-cli/ghcp_conversation/manifest.json` AND `copilot-cli/ghcp_conversation/acp_client.py`

## CHANGELOG
- Update `copilot-cli/CHANGELOG.md` with new version section at TOP
- Use `##` for version heading, `###` for category, `-` for items
- Bold the key change: `- **Fix: description** — details`

## Git Commands
```
git add -A
git commit -m "type: description (vX.Y.Z)"
git tag -a vX.Y.Z -m "vX.Y.Z: summary"
git push origin main --tags
```

## Verify After Push
```powershell
Select-String -Pattern '"version"' custom_components\ghcp_conversation\manifest.json
Select-String -Pattern '"version"' copilot-cli\ghcp_conversation\manifest.json
Select-String -Pattern '^version' copilot-cli\config.yaml
Get-ChildItem -Path custom_components\ghcp_conversation\*.py, copilot-cli\ghcp_conversation\*.py | Select-String -Pattern 'CLIENT_VERSION'
```
