"""Salidas CDK compatibles con el stack original y el stack de recuperacion."""
import json
from pathlib import Path


def load_outputs(path="cdk-outputs.json"):
    values = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    matches = [value for value in values.values()
               if isinstance(value, dict) and {"ApiId", "TableName"}.issubset(value)]
    if len(matches) != 1:
        raise RuntimeError("No se encontro un unico stack de facturacion en las salidas CDK")
    return matches[0]
