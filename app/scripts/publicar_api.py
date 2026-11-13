"""Publica prod por SDK para evitar el proveedor Stage de CloudFormation local."""
import json
import os
import sys
from urllib.parse import urlparse

from local_outputs import load_outputs


def check_local_endpoint(endpoint):
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"emulador", "localhost", "127.0.0.1"} or parsed.port != 4566:
        raise RuntimeError("Esta operacion solo admite el emulador local en el puerto 4566")


def publish(outputs, client):
    api_id = outputs["ApiId"]
    deployment_id = outputs["ApiDeploymentId"]
    stage_name = outputs.get("StageName", "prod")
    if stage_name != "prod":
        raise RuntimeError("La recuperacion solo administra la etapa prod del proyecto")
    # Confirma primero que el deployment corresponde a esta API.
    client.get_deployment(restApiId=api_id, deploymentId=deployment_id)
    try:
        current = client.get_stage(restApiId=api_id, stageName=stage_name)
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") != "NotFoundException":
            raise
        client.create_stage(restApiId=api_id, stageName=stage_name, deploymentId=deployment_id)
        action = "creada"
    else:
        if current.get("deploymentId") != deployment_id:
            client.update_stage(restApiId=api_id, stageName=stage_name, patchOperations=[{
                "op": "replace", "path": "/deploymentId", "value": deployment_id,
            }])
            action = "actualizada"
        else:
            action = "sin cambios"
    final = client.get_stage(restApiId=api_id, stageName=stage_name)
    if final.get("deploymentId") != deployment_id:
        raise RuntimeError("La etapa prod no quedo asociada al deployment esperado")
    return {"estado": "ok", "etapa": stage_name, "accion": action, "api_id": api_id,
            "stack": outputs.get("ActiveStackName", "FacturacionStack")}


if __name__ == "__main__":
    try:
        check_local_endpoint(os.environ.get("AWS_ENDPOINT_URL", ""))
        import boto3
        print(json.dumps(publish(load_outputs(), boto3.client("apigateway")), indent=2))
    except Exception as exc:
        print(f"No se pudo publicar el API local: {exc}", file=sys.stderr)
        sys.exit(1)
