# Deferred local validation

These checks remain pending until the user can access their Windows machine.
Remind the user at the next local setup/validation session; continue independent
development without repeating the request in the meantime.

- [ ] Confirm Windows API access from PowerShell:

  ```powershell
  Invoke-RestMethod http://127.0.0.1:11434/api/tags |
      Select-Object -ExpandProperty models |
      Select-Object name
  ```

- [ ] Confirm the actual installed Qwen model tag and set `OLLAMA_MODEL` accordingly.
- [ ] Verify Docker access with `docker compose run --rm worker` after local startup.
- [ ] If access fails, distinguish a Windows listener from a WSL-only listener
  using [the development guide](DEVELOPMENT.md); reuse a verified reachable endpoint.
- [ ] Verify Windows Docker Desktop startup and persistent volumes.

Ollama is the existing native application. Odysseus remains its separate interface.
Cloud fixtures do not establish that these local checks have passed. No scheduled
notification has been created; this checklist records the reminder for continued
development and local testing.
