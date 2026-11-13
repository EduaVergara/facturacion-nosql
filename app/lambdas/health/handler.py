"""Diagnóstico con tiempos acotados y errores de infraestructura sanitizados."""
import json
import logging
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def dynamodb_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "dynamodb",
        config=Config(connect_timeout=0.5, read_timeout=0.5, retries={"total_max_attempts": 1}),
    )


def redis_client():
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    timeout = float(os.environ.get("REDIS_TIMEOUT_SECONDS", "0.2"))
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        decode_responses=True,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        retry=Retry(NoBackoff(), 0),
    )


def check_dynamodb():
    client = None
    try:
        client = dynamodb_client()
        table = client.describe_table(TableName=os.environ["TABLE_NAME"])["Table"]
        expected = set(os.environ.get("EXPECTED_INDEXES", "GSI1,GSI2,GSI3").split(","))
        available = {
            index["IndexName"] for index in table.get("GlobalSecondaryIndexes", [])
            if index.get("IndexStatus") == "ACTIVE"
        }
        if table.get("TableStatus") != "ACTIVE" or not expected.issubset(available):
            return {"estado": "error", "detalle": "Tabla o indices todavia no disponibles"}
        return {"estado": "ok", "tabla": table["TableName"], "indices": sorted(expected)}
    except Exception:
        logger.exception("No fue posible comprobar DynamoDB")
        return {"estado": "error", "detalle": "DynamoDB no disponible"}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("No fue posible cerrar el cliente DynamoDB")


def check_redis():
    client = None
    try:
        client = redis_client()
        if not client.ping():
            return {"estado": "error", "detalle": "Redis no respondio al ping"}
        return {"estado": "ok"}
    except Exception:
        logger.exception("No fue posible comprobar Redis")
        return {"estado": "error", "detalle": "Redis no disponible"}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.warning("No fue posible cerrar el cliente Redis")


def main(event, context):
    dynamodb_status = check_dynamodb()
    redis_status = check_redis()
    ready = dynamodb_status["estado"] == redis_status["estado"] == "ok"
    headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
    origin = os.environ.get("FRONTEND_ORIGIN")
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Vary"] = "Origin"
    return {
        "statusCode": 200 if ready else 503,
        "headers": headers,
        "body": json.dumps({
            "servicio": "facturacion-nosql",
            "etapa": 6,
            "estado": "ok" if ready else "degradado",
            "dynamodb": dynamodb_status,
            "redis": redis_status,
        }, ensure_ascii=False),
    }
