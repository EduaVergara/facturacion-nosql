"""Pruebas de respuestas y fallos, ejecutables sin librerias externas."""
import json
import os
import unittest
from unittest.mock import Mock, patch

from lambdas.health import handler


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "TABLE_NAME": "Facturacion",
            "EXPECTED_INDEXES": "GSI1,GSI2,GSI3",
            "FRONTEND_ORIGIN": "http://localhost:8080",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def table_response(self):
        return {"Table": {"TableName": "Facturacion", "TableStatus": "ACTIVE",
                "GlobalSecondaryIndexes": [
                    {"IndexName": name, "IndexStatus": "ACTIVE"}
                    for name in ("GSI1", "GSI2", "GSI3")
                ]}}

    def test_table_and_three_indexes_ready(self):
        client = Mock()
        client.describe_table.return_value = self.table_response()
        with patch.object(handler, "dynamodb_client", return_value=client):
            result = handler.check_dynamodb()
        self.assertEqual(result["estado"], "ok")
        self.assertEqual(result["indices"], ["GSI1", "GSI2", "GSI3"])
        client.describe_table.assert_called_once_with(TableName="Facturacion")
        client.close.assert_called_once()

    def test_missing_index_does_not_report_ready(self):
        client = Mock()
        result = self.table_response()
        result["Table"]["GlobalSecondaryIndexes"].pop()
        client.describe_table.return_value = result
        with patch.object(handler, "dynamodb_client", return_value=client):
            self.assertEqual(handler.check_dynamodb()["estado"], "error")

    def test_building_index_does_not_report_ready(self):
        client = Mock()
        result = self.table_response()
        result["Table"]["GlobalSecondaryIndexes"][0]["IndexStatus"] = "CREATING"
        client.describe_table.return_value = result
        with patch.object(handler, "dynamodb_client", return_value=client):
            self.assertEqual(handler.check_dynamodb()["estado"], "error")

    def test_table_still_creating_does_not_report_ready(self):
        client = Mock()
        result = self.table_response()
        result["Table"]["TableStatus"] = "CREATING"
        client.describe_table.return_value = result
        with patch.object(handler, "dynamodb_client", return_value=client):
            self.assertEqual(handler.check_dynamodb()["estado"], "error")

    def test_database_failure_closes_client_and_hides_details(self):
        client = Mock()
        client.describe_table.side_effect = RuntimeError("internal-private-detail")
        with patch.object(handler, "dynamodb_client", return_value=client), self.assertLogs(handler.logger):
            result = handler.check_dynamodb()
        self.assertEqual(result["estado"], "error")
        self.assertNotIn("internal-private-detail", json.dumps(result))
        client.close.assert_called_once()

    def test_client_creation_failure_is_a_diagnostic_error(self):
        with patch.object(handler, "dynamodb_client", side_effect=TimeoutError()), self.assertLogs(handler.logger):
            self.assertEqual(handler.check_dynamodb()["estado"], "error")

    def test_redis_ping_success_closes_connection(self):
        client = Mock()
        client.ping.return_value = True
        with patch.object(handler, "redis_client", return_value=client):
            self.assertEqual(handler.check_redis()["estado"], "ok")
        client.close.assert_called_once()

    def test_redis_false_ping_is_not_a_success(self):
        client = Mock()
        client.ping.return_value = False
        with patch.object(handler, "redis_client", return_value=client):
            self.assertEqual(handler.check_redis()["estado"], "error")

    def test_redis_unavailable_is_a_diagnostic_error(self):
        client = Mock()
        client.ping.side_effect = TimeoutError()
        with patch.object(handler, "redis_client", return_value=client), self.assertLogs(handler.logger):
            self.assertEqual(handler.check_redis()["estado"], "error")
        client.close.assert_called_once()

    def test_ready_returns_200_and_json_and_specific_origin(self):
        with patch.object(handler, "check_dynamodb", return_value={"estado": "ok"}), \
             patch.object(handler, "check_redis", return_value={"estado": "ok"}):
            response = handler.main({}, None)
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(json.loads(response["body"])["estado"], "ok")
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "http://localhost:8080")
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_redis_failure_returns_503_with_database_status(self):
        with patch.object(handler, "check_dynamodb", return_value={"estado": "ok"}), \
             patch.object(handler, "check_redis", return_value={"estado": "error"}):
            response = handler.main({}, None)
        self.assertEqual(response["statusCode"], 503)
        self.assertEqual(json.loads(response["body"])["dynamodb"]["estado"], "ok")

    def test_database_failure_returns_503_even_when_redis_works(self):
        with patch.object(handler, "check_dynamodb", return_value={"estado": "error"}), \
             patch.object(handler, "check_redis", return_value={"estado": "ok"}):
            self.assertEqual(handler.main({}, None)["statusCode"], 503)
