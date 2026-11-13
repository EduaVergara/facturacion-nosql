"""Adaptador de lecturas fuertes y TransactWriteItems, sin depender de Redis."""
import logging
import os

from catalogo.model import ApiError, json_numbers

logger = logging.getLogger(__name__)


class CommitConflict(Exception):
    def __init__(self, kind):
        super().__init__(kind)
        self.kind = kind


def transaction_actions(table_name, document, receipt, products, customer, box, encode):
    actions = [{"Put": {"TableName": table_name, "Item": encode(item),
                         "ConditionExpression": "attribute_not_exists(PK)"}}
               for item in (document, receipt)]
    references = [(item, True) for item in products.values()] + [(customer, False), (box, True)]
    for item, require_active in references:
        names, values = {}, {}
        condition = "attribute_exists(PK)"
        if "version" in item:
            names["#v"] = "version"
            values[":v"] = item["version"]
            condition += " AND #v = :v"
        if require_active:
            names["#a"] = "activo"
            values[":a"] = True
            condition += " AND #a = :a"
        check = {"TableName": table_name, "Key": encode({"PK": item["PK"], "SK": item["SK"]}),
                 "ConditionExpression": condition}
        if names:
            check["ExpressionAttributeNames"] = names
        if values:
            check["ExpressionAttributeValues"] = encode(values)
        actions.append({"ConditionCheck": check})
    return actions


class InvoiceRepository:
    def __init__(self, client=None, table_name=None):
        import boto3
        from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
        from botocore.config import Config

        self.client = client if client is not None else boto3.client("dynamodb", config=Config(
            connect_timeout=1, read_timeout=2, retries={"total_max_attempts": 1}))
        self.table_name = table_name or os.environ.get("TABLE_NAME", "Facturacion")
        self.serializer = TypeSerializer()
        self.deserializer = TypeDeserializer()

    def encode(self, item):
        return {key: self.serializer.serialize(value) for key, value in item.items()}

    def get(self, pk, sk):
        try:
            response = self.client.get_item(TableName=self.table_name,
                Key=self.encode({"PK": pk, "SK": sk}), ConsistentRead=True)
            raw = response.get("Item")
            return None if raw is None else json_numbers({k: self.deserializer.deserialize(v) for k, v in raw.items()})
        except Exception as exc:
            logger.exception("No se completo una lectura de facturacion")
            raise ApiError(503, "No se pudo consultar la base de datos; conserva la solicitud para reintentar") from exc

    def history_query(self, spec, limit, cursor):
        request = {
            "TableName": self.table_name, "IndexName": spec.index,
            "KeyConditionExpression": "#pk = :pk AND #sk BETWEEN :lo AND :hi",
            "ExpressionAttributeNames": {"#pk": f"{spec.index}PK", "#sk": f"{spec.index}SK",
                "#id": "factura_id", "#fecha": "fecha_utc", "#caja": "caja_id",
                "#cliente": "cliente_id", "#total": "total_centavos"},
            "ExpressionAttributeValues": self.encode({":pk": spec.partition, ":lo": spec.lower, ":hi": spec.upper}),
            "ProjectionExpression": "#id, #fecha, #caja, #cliente, #total",
            "ScanIndexForward": False, "Limit": limit,
        }
        if cursor:
            request["ExclusiveStartKey"] = self.encode(cursor)
        try:
            response = self.client.query(**request)
            def decode(item):
                return json_numbers({key: self.deserializer.deserialize(value) for key, value in item.items()})
            return [decode(item) for item in response.get("Items", [])], (
                decode(response["LastEvaluatedKey"]) if response.get("LastEvaluatedKey") else None)
        except Exception as exc:
            logger.exception("No se pudo consultar el historial por indice")
            raise ApiError(503, "No fue posible consultar el historial; vuelve a intentarlo") from exc

    def commit(self, document, receipt, products, customer, box, token):
        actions = transaction_actions(self.table_name, document, receipt, products, customer, box, self.encode)
        try:
            self.client.transact_write_items(TransactItems=actions, ClientRequestToken=token)
        except Exception as exc:
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code", "")
            if code == "TransactionCanceledException":
                reasons = {item.get("Code") for item in response.get("CancellationReasons", [])}
                if "ConditionalCheckFailed" in reasons:
                    raise CommitConflict("conditional") from exc
                if not reasons or reasons <= {None, "None", "TransactionConflict", "ProvisionedThroughputExceeded", "ThrottlingError"}:
                    raise CommitConflict("retryable") from exc
            if code in {"TransactionConflictException", "TransactionInProgressException", "ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"}:
                raise CommitConflict("retryable") from exc
            logger.exception("No se pudo confirmar la transaccion de venta")
            raise ApiError(503, "No se pudo confirmar la venta; reintenta con la misma solicitud_id y cuerpo") from exc
