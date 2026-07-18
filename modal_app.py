"""
Modal deployment wrapper for glc_v1  (Session 12, Move 1: wrap the gateway).

This file changes NO application code. It only describes, for Modal:
  1. the container image to build,
  2. a persistent Volume for the ~/.glc config/db folder,
  3. a Secret that supplies the provider keys as environment variables,
  4. which object to serve  ->  the existing FastAPI app, glc.main:app.

Deploy with:   uv run modal deploy modal_app.py
"""

from pathlib import Path

import modal

# The Modal "app" is just a namespace for everything we deploy under this name.
app = modal.App("glc-v1-gateway")
ADAPTER_SANDBOX_APP_NAME = "glc-v1-adapters"

# Path to the glc package next to this file. We copy the whole package (not just
# .py files) so its data files travel too: policy.yaml, channels.yaml,
# audit/schema.sql, and the channel catalogue.
LOCAL_GLC = Path(__file__).parent / "glc"

# The image = a Linux box with Python 3.11, the same dependencies as
# pyproject.toml, the glc package copied in, and GLC_CONFIG_DIR pointed at the
# Volume mount so all databases land on persistent storage instead of the
# throwaway container filesystem.
gateway_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "fastapi>=0.110",
        "uvicorn[standard]>=0.27",
        "httpx>=0.27",
        "python-dotenv>=1.0",
        "pydantic>=2.6",
        "jsonschema>=4.21",
        "pyyaml>=6.0",
        "websockets>=12.0",
        "twilio>=9.0",
    )
    .env({"GLC_CONFIG_DIR": "/data/glc", "GLC_ENV": "production"})
    .add_local_dir(str(LOCAL_GLC), remote_path="/root/glc")
)

# Adapter sandboxes run in a separate image boundary from the gateway app.
adapter_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "httpx>=0.27",
        "python-dotenv>=1.0",
        "pydantic>=2.6",
        "pyyaml>=6.0",
        "websockets>=12.0",
        "twilio>=9.0",
    )
    .env({"GLC_CONFIG_DIR": "/data/glc", "GLC_ENV": "production"})
    .add_local_dir(str(LOCAL_GLC), remote_path="/root/glc")
)

# A persistent Volume. The audit db, pairing db, and install token live here and
# survive restarts and redeploys. Without this, every restart wipes them.
data_volume = modal.Volume.from_name("glc-data", create_if_missing=True)

# The provider keys, injected as environment variables at runtime. Created
# separately with `modal secret create glc-llm-keys ...` (mock values for now).
llm_secret = modal.Secret.from_name("glc-llm-keys")

# Outbound egress policy for adapter sandboxes. Keep this list narrow: only
# known LLM provider API domains required by the gateway's model backends.
LLM_PROVIDER_EGRESS_ALLOWLIST = (
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "integrate.api.nvidia.com",
    "api.cerebras.ai",
    "openrouter.ai",
    "models.github.ai",
)

# Only known adapter modules can be launched through this helper.
ADAPTER_MODULE_ALLOWLIST = {
    "discord": "glc.channels.catalogue.discord.adapter",
    "gmail": "glc.channels.catalogue.gmail.adapter",
    "imap": "glc.channels.catalogue.imap.adapter",
    "line": "glc.channels.catalogue.line.adapter",
    "local_mic": "glc.channels.catalogue.local_mic.adapter",
    "matrix": "glc.channels.catalogue.matrix.adapter",
    "signal": "glc.channels.catalogue.signal.adapter",
    "slack": "glc.channels.catalogue.slack.adapter",
    "teams": "glc.channels.catalogue.teams.adapter",
    "telegram": "glc.channels.catalogue.telegram.adapter",
    "twilio_sms": "glc.channels.catalogue.twilio_sms.adapter",
    "twilio_voice": "glc.channels.catalogue.twilio_voice.adapter",
    "webhook": "glc.channels.catalogue.webhook.adapter",
    "webui": "glc.channels.catalogue.webui.adapter",
    "whatsapp": "glc.channels.catalogue.whatsapp.adapter",
}

# Adapters that should never require outbound internet access from the runtime.
NO_EGRESS_ADAPTERS = {
    "local_mic",
}


def _adapter_sandbox_env() -> dict[str, str]:
    return {
        "GLC_CONFIG_DIR": "/data/glc",
        "GLC_ENV": "production",
    }


def _adapter_sandbox_app() -> modal.App:
    # Sandboxes launched under this dedicated app are isolated from gateway
    # serving containers and run in their own container PID namespaces.
    return modal.App.lookup(ADAPTER_SANDBOX_APP_NAME, create_if_missing=True)


@app.function(
    image=gateway_image,
    volumes={"/data": data_volume},
    secrets=[llm_secret],
)
def launch_adapter_sandbox(adapter_name: str, timeout_s: int = 600) -> str:
    """Launch an adapter in an isolated Modal Sandbox with strict egress.

    This is a process-boundary hardening step: adapter code runs in a separate
    runtime where outbound network access is constrained to approved domains.
    """
    module = ADAPTER_MODULE_ALLOWLIST.get(adapter_name)
    if module is None:
        raise ValueError(f"Unsupported adapter_name: {adapter_name}")

    cmd = ["python", "-I", "-m", module]

    sandbox_network_kwargs = {
        "block_network": False,
        "outbound_domain_allowlist": list(LLM_PROVIDER_EGRESS_ALLOWLIST),
    }
    if adapter_name in NO_EGRESS_ADAPTERS:
        sandbox_network_kwargs = {"block_network": True}

    sb = modal.Sandbox.create(
        *cmd,
        app=_adapter_sandbox_app(),
        image=adapter_image,
        volumes={"/data": data_volume},
        secrets=[llm_secret],
        env=_adapter_sandbox_env(),
        timeout=max(60, int(timeout_s)),
        **sandbox_network_kwargs,
    )
    sb.detach()
    return sb.object_id


@app.function(
    image=gateway_image,
    volumes={"/data": data_volume},
    secrets=[llm_secret],
    min_containers=0,  # scale to zero when idle -> protects the free tier
)
@modal.asgi_app()
def fastapi_app():
    """Serve the unchanged glc_v1 FastAPI app."""
    import os

    # The gateway writes its databases and install token here on startup, so the
    # folder must exist on the mounted Volume before the app's lifespan runs.
    os.makedirs("/data/glc", exist_ok=True)

    from glc.main import app as web  # the real glc_v1 app, imported as-is

    return web
