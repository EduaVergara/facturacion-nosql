"""Adaptador DynamoDB con lecturas por clave y escrituras condicionales."""
import logging
import os

from .model import ApiError

logger = logging.getLogger(__name__)


class DynamoRepository:
    def __init__(self, table=None):
        if table is None:
            import boto3
            from botocore.config import Config
            resource = boto3.resource("dynamodb", config=Config(
                connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 2},
            ))
            table = resource.Table(os.environ.get("TABLE_NAME", "Facturacion"))
        self.table = table

    def get(self, pk, sk):
        try:
            return self.table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True).get("Item")
        except Exception as exc:
            raise self._error(exc) from exc

    def put(self, item, expected_version=None):
        request = {"Item": item, "ConditionExpression": "attribute_not_exists(PK)"}
        if expected_version is not None:
            request.update(
                ConditionExpression="attribute_exists(PK) AND #v = :expected",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":expected": expected_version},
            )
        try:
            self.table.put_item(**request)
        except Exception as exc:
            raise self._error(exc) from exc

    def query(self, scope, limit, cursor):
        parameters = {"Limit": limit, "ScanIndexForward": True}
        if scope == "CAJAS":
            parameters.update(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={":pk": "CONFIG#CAJAS", ":prefix": "CAJA#"},
                ConsistentRead=True,
            )
        else:
            partition = {"PRODUCTOS": "CATALOGO#PRODUCTOS", "CLIENTES": "DIRECTORIO#CLIENTES"}[scope]
            parameters.update(
                IndexName="GSI1", KeyConditionExpression="GSI1PK = :pk",
                ExpressionAttributeValues={":pk": partition},
            )
        if cursor:
            parameters["ExclusiveStartKey"] = cursor
        try:
            response = self.table.query(**parameters)
            return response.get("Items", []), response.get("LastEvaluatedKey")
        except Exception as exc:
            raise self._error(exc) from exc

    @staticmethod
    def _error(exc):
        if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return ApiError(409, "El registro ya existe o su version cambio; vuelve a consultarlo")
        logger.exception("Operacion DynamoDB no completada")
        return ApiError(503, "No fue posible completar la operacion en la base de datos")
