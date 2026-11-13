"""Entrada CDK limitada al entorno local acordado."""
import os
import json
from pathlib import Path
from urllib.parse import urlparse

import aws_cdk as cdk

from infra.stack import FacturacionStack

endpoint = urlparse(os.environ.get("AWS_ENDPOINT_URL", ""))
if endpoint.scheme != "http" or endpoint.hostname not in {"emulador", "localhost", "127.0.0.1"}:
    raise RuntimeError("Ejecuta CDK dentro de cdk-dev, con AWS_ENDPOINT_URL del emulador local.")

config_path = Path(__file__).resolve().parents[1] / "local-config.json"
config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
if type(config.get("use_existing_table", False)) is not bool:
    raise RuntimeError("use_existing_table debe ser un booleano")

app = cdk.App()
FacturacionStack(
    app,
    "FacturacionStack",
    stack_name=config.get("stack_name", "FacturacionStack"),
    existing_table=config.get("use_existing_table", False),
    env=cdk.Environment(account="000000000000", region="us-east-1"),
)
app.synth()
