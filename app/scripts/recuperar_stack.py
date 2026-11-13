"""Respalda la tabla y configura un stack nuevo sin eliminar recursos existentes."""
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from publicar_api import check_local_endpoint


def json_default(value):
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"No se puede respaldar el tipo {type(value).__name__}")


def table_snapshot(client):
    description = client.describe_table(TableName="Facturacion")["Table"]
    if description.get("TableStatus") != "ACTIVE":
        raise RuntimeError("La tabla Facturacion no esta ACTIVE; no se cambio la configuracion")
    keys = {item["AttributeName"]: item["KeyType"] for item in description["KeySchema"]}
    indexes = {item["IndexName"] for item in description.get("GlobalSecondaryIndexes", [])
               if item.get("IndexStatus") == "ACTIVE"}
    if keys != {"PK": "HASH", "SK": "RANGE"} or indexes != {"GSI1", "GSI2", "GSI3"}:
        raise RuntimeError("El esquema de la tabla no coincide con el proyecto")
    items = []
    cursor = None
    while True:
        request = {"TableName": "Facturacion", "ConsistentRead": True}
        if cursor:
            request["ExclusiveStartKey"] = cursor
        page = client.scan(**request)
        items.extend(page.get("Items", []))
        cursor = page.get("LastEvaluatedKey")
        if not cursor:
            break
    return {"format": "DynamoDB AttributeValue JSON; binary values are base64",
            "table": description, "items": items, "item_count": len(items)}


def choose_stack(cloudformation, candidate, stamp):
    try:
        state = cloudformation.describe_stacks(StackName=candidate)["Stacks"][0]["StackStatus"]
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if error.get("Code") == "ValidationError" and "does not exist" in error.get("Message", "").lower():
            return candidate
        raise
    if state in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
        return candidate
    if state in {"ROLLBACK_COMPLETE", "CREATE_FAILED"}:
        alternative = "FacturacionServiciosStack-" + stamp
        # No se modifican ni se eliminan los stacks fallidos.
        try:
            cloudformation.describe_stacks(StackName=alternative)
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") == "ValidationError" and "does not exist" in error.get("Message", "").lower():
                return alternative
            raise
        raise RuntimeError("Ya existe el nombre alternativo; repite la recuperacion mas tarde")
    raise RuntimeError(f"El stack {candidate} esta en {state}; espera o revisa ese estado antes de continuar")


def prepare(directory, dynamodb, cloudformation, endpoint):
    check_local_endpoint(endpoint)
    directory = Path(directory)
    config_path = directory / "local-config.json"
    previous = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    snapshot = table_snapshot(dynamodb)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    candidate = previous.get("stack_name", "FacturacionServiciosStack")
    if candidate == "FacturacionStack":
        candidate = "FacturacionServiciosStack"
    if not isinstance(candidate, str) or not candidate.startswith("FacturacionServiciosStack"):
        raise RuntimeError("El nombre del stack de servicios no es el esperado")
    selected = choose_stack(cloudformation, candidate, stamp)
    backup_dir = directory / "backups" / ("recuperacion-" + stamp)
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_file = backup_dir / "Facturacion.backup.json"
    backup_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    (backup_dir / "config-anterior.json").write_text(json.dumps(previous, indent=2), encoding="utf-8")
    # Se verifica la copia escrita antes de cambiar el stack de destino.
    saved = json.loads(backup_file.read_text(encoding="utf-8"))
    if saved["item_count"] != len(saved["items"]) or saved["item_count"] != snapshot["item_count"]:
        raise RuntimeError("El respaldo no pudo verificarse; no se cambio la configuracion")
    config = {**previous, "use_existing_table": True, "stack_name": selected}
    temporary = config_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    temporary.replace(config_path)
    return {"estado": "preparado", "tabla": "Facturacion", "registros_respaldados": snapshot["item_count"],
            "respaldo": str(backup_file), "stack_servicios": selected,
            "recursos_eliminados": 0}


if __name__ == "__main__":
    try:
        check_local_endpoint(os.environ.get("AWS_ENDPOINT_URL", ""))
        import boto3
        from botocore.config import Config
        sdk_config = Config(connect_timeout=2, read_timeout=5, retries={"total_max_attempts": 2})
        report = prepare(Path(__file__).resolve().parents[1],
                         boto3.client("dynamodb", config=sdk_config),
                         boto3.client("cloudformation", config=sdk_config),
                         os.environ["AWS_ENDPOINT_URL"])
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"No se pudo preparar la recuperacion: {exc}", file=sys.stderr)
        sys.exit(1)
