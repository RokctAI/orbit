# Orbit

OSS client daemon for [Gravity](https://github.com/RokctAI/gravity). Install, connect, and edit repos in any IDE.

## Install

```bash
pip install -e .
```

## Usage

```bash
orbit login          # Authenticate with Gravity server
orbit mount          # Fetch allowed repos → local workspace
orbit status         # Show connection and sync state
```

## Phase 2

Orbit connects to a Gravity server (FastAPI) running on your VPS. In Phase 1, only Gravity's local CLI is functional. Orbit commands are placeholders that will be implemented when Gravity gains its server mode.
