"""Comprueba recursos reales del emulador. Ejecutar dentro de cdk-dev."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import boto3
import redis
from botocore.config import Config
from local_outputs import load_outputs
from local_http import request_json


def verify(outputs_path):
    outputs = load_outputs(outputs_path)
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://emulador:4566").rstrip("/")
    client = boto3.client("dynamodb", config=Config(
        connect_timeout=2, read_timeout=2, retries={"total_max_attempts": 1},
    ))
    try:
        table = client.describe_table(TableName=outputs["TableName"])["Table"]
        expected_keys = {"PK": "HASH", "SK": "RANGE"}
        actual_keys = {key["AttributeName"]: key["KeyType"] for key in table["KeySchema"]}
        if actual_keys != expected_keys:
            raise RuntimeError("La tabla no tiene las claves PK y SK previstas")
        indexes = {i["IndexName"]: i for i in table.get("GlobalSecondaryIndexes", [])}
        if set(indexes) != {"GSI1", "GSI2", "GSI3"}:
            raise RuntimeError("No aparecen los tres indices previstos")
        for name, index in indexes.items():
            if index.get("IndexStatus") != "ACTIVE":
                raise RuntimeError(f"{name} aun no esta activo")
            if index["Projection"]["ProjectionType"] != "INCLUDE":
                raise RuntimeError(f"Proyeccion inesperada en {name}")
    finally:
        client.close()

    cache = redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        decode_responses=True, socket_connect_timeout=1, socket_timeout=1,
    )
    # Solo se modifica esta clave temporal de diagnostico, con TTL corto.
    key = f"facturacion:diagnostico:{uuid.uuid4()}"
    try:
        cache.set(key, "ok", ex=20)
        if cache.get(key) != "ok" or cache.ttl(key) <= 0:
            raise RuntimeError("Redis no conserva el valor con TTL")
    finally:
        try:
            cache.delete(key)
        finally:
            cache.close()

    url = f"{endpoint}/restapis/{outputs['ApiId']}/prod/_user_request_/health"
    _, health, _ = request_json(url)
    if health.get("estado") != "ok":
        raise RuntimeError("El health check no confirma todos los servicios")
    return {"estado": "ok", "tabla": outputs["TableName"],
            "indices": sorted(indexes), "redis_lectura_escritura_ttl": "ok",
            "api_health": health}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", default="cdk-outputs.json")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.outputs), indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"Comprobacion incompleta: {exc}", file=sys.stderr)
        sys.exit(1)
