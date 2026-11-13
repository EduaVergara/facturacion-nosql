"""Recuperacion sin mutaciones sobre tablas o stacks existentes."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local_outputs import load_outputs
from publicar_api import check_local_endpoint, publish
from recuperar_stack import choose_stack, prepare, table_snapshot


class ServiceError(Exception):
    def __init__(self, code, message=""):
        self.response = {"Error": {"Code": code, "Message": message}}


def table_description():
    return {"TableName": "Facturacion", "TableStatus": "ACTIVE",
            "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            "GlobalSecondaryIndexes": [{"IndexName": name, "IndexStatus": "ACTIVE"} for name in ("GSI1", "GSI2", "GSI3")]}


class RecoveryTests(unittest.TestCase):
    def clients(self):
        db = Mock(spec=["describe_table", "scan"])
        db.describe_table.return_value = {"Table": table_description()}
        db.scan.return_value = {"Items": [{"PK": {"S": "PRODUCTO#demo"}, "SK": {"S": "DATOS"}, "precio": {"N": "12345"}}]}
        cf = Mock(spec=["describe_stacks"])
        cf.describe_stacks.side_effect = ServiceError("ValidationError", "Stack does not exist")
        return db, cf

    def test_backup_before_config_and_no_destructive_clients(self):
        db, cf = self.clients()
        with tempfile.TemporaryDirectory() as directory:
            report = prepare(directory, db, cf, "http://emulador:4566")
            backup = json.loads(Path(report["respaldo"]).read_text())
            config = json.loads((Path(directory) / "local-config.json").read_text())
            self.assertEqual(backup["item_count"], 1)
            self.assertEqual(backup["items"][0]["precio"], {"N": "12345"})
            self.assertTrue(config["use_existing_table"])
            self.assertEqual(config["stack_name"], "FacturacionServiciosStack")
            self.assertEqual(report["recursos_eliminados"], 0)
            self.assertEqual(db.method_calls[0][0], "describe_table")
            self.assertEqual({call[0] for call in db.method_calls}, {"describe_table", "scan"})
            self.assertEqual({call[0] for call in cf.method_calls}, {"describe_stacks"})

    def test_backup_reads_every_page(self):
        db, _ = self.clients()
        cursor = {"PK": {"S": "P#1"}, "SK": {"S": "D"}}
        db.scan.side_effect = [{"Items": [cursor], "LastEvaluatedKey": cursor},
                               {"Items": [{"PK": {"S": "P#2"}, "SK": {"S": "D"}}]}]
        self.assertEqual(table_snapshot(db)["item_count"], 2)
        self.assertEqual(db.scan.call_args_list[1].kwargs["ExclusiveStartKey"], cursor)

    def test_inactive_table_never_changes_config(self):
        db, cf = self.clients()
        db.describe_table.return_value["Table"]["TableStatus"] = "CREATING"
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RuntimeError):
            prepare(directory, db, cf, "http://emulador:4566")
            self.fail("No debe continuar")
        db.scan.assert_not_called()
        cf.describe_stacks.assert_not_called()

    def test_unexpected_schema_stops_before_scan(self):
        db, _ = self.clients()
        db.describe_table.return_value["Table"]["GlobalSecondaryIndexes"].pop()
        with self.assertRaises(RuntimeError):
            table_snapshot(db)
        db.scan.assert_not_called()

    def test_scan_failure_does_not_change_existing_config(self):
        db, cf = self.clients()
        db.scan.side_effect = RuntimeError("fallo de lectura")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local-config.json"
            path.write_text('{"campo":"conservar"}')
            with self.assertRaises(RuntimeError):
                prepare(directory, db, cf, "http://emulador:4566")
            self.assertEqual(json.loads(path.read_text()), {"campo": "conservar"})

    def test_remote_endpoint_does_not_call_any_service(self):
        db, cf = self.clients()
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(RuntimeError):
            prepare(directory, db, cf, "https://dynamodb.us-east-1.amazonaws.com")
        db.describe_table.assert_not_called()
        cf.describe_stacks.assert_not_called()

    def test_repeated_preparation_reuses_active_services_stack(self):
        db, cf = self.clients()
        with tempfile.TemporaryDirectory() as directory:
            first = prepare(directory, db, cf, "http://emulador:4566")
            cf.describe_stacks.side_effect = None
            cf.describe_stacks.return_value = {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]}
            second = prepare(directory, db, cf, "http://emulador:4566")
            self.assertEqual(first["stack_servicios"], second["stack_servicios"])
            self.assertNotEqual(first["respaldo"], second["respaldo"])

    def test_failed_services_stack_gets_new_name(self):
        _, cf = self.clients()
        cf.describe_stacks.side_effect = [{"Stacks": [{"StackStatus": "ROLLBACK_COMPLETE"}]},
                                         ServiceError("ValidationError", "Stack does not exist")]
        self.assertEqual(choose_stack(cf, "FacturacionServiciosStack", "12345"), "FacturacionServiciosStack-12345")

    def test_running_stack_requires_waiting(self):
        _, cf = self.clients()
        cf.describe_stacks.side_effect = None
        cf.describe_stacks.return_value = {"Stacks": [{"StackStatus": "UPDATE_IN_PROGRESS"}]}
        with self.assertRaises(RuntimeError):
            choose_stack(cf, "FacturacionServiciosStack", "12345")


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.outputs = {"ApiId": "api-demo", "ApiDeploymentId": "deploy-new", "StageName": "prod"}
        self.client = Mock(spec=["get_deployment", "get_stage", "create_stage", "update_stage"])

    def test_missing_stage_is_created_after_deployment_validation(self):
        self.client.get_stage.side_effect = [ServiceError("NotFoundException"), {"deploymentId": "deploy-new"}]
        result = publish(self.outputs, self.client)
        self.assertEqual(result["accion"], "creada")
        self.client.create_stage.assert_called_once_with(restApiId="api-demo", stageName="prod", deploymentId="deploy-new")
        self.assertEqual(self.client.method_calls[0][0], "get_deployment")

    def test_existing_stage_is_updated_without_delete_or_create(self):
        self.client.get_stage.side_effect = [{"deploymentId": "old"}, {"deploymentId": "deploy-new"}]
        result = publish(self.outputs, self.client)
        self.assertEqual(result["accion"], "actualizada")
        self.client.create_stage.assert_not_called()
        self.client.update_stage.assert_called_once_with(restApiId="api-demo", stageName="prod", patchOperations=[{
            "op": "replace", "path": "/deploymentId", "value": "deploy-new"}])

    def test_repeated_publication_is_idempotent(self):
        self.client.get_stage.return_value = {"deploymentId": "deploy-new"}
        self.assertEqual(publish(self.outputs, self.client)["accion"], "sin cambios")
        self.client.create_stage.assert_not_called()
        self.client.update_stage.assert_not_called()

    def test_service_error_is_not_interpreted_as_missing_stage(self):
        self.client.get_stage.side_effect = ServiceError("AccessDeniedException")
        with self.assertRaises(ServiceError):
            publish(self.outputs, self.client)
        self.client.create_stage.assert_not_called()

    def test_wrong_final_deployment_is_reported(self):
        self.client.get_stage.side_effect = [{"deploymentId": "old"}, {"deploymentId": "still-old"}]
        with self.assertRaises(RuntimeError):
            publish(self.outputs, self.client)

    def test_old_and_new_output_stack_names_are_supported(self):
        for name in ("FacturacionStack", "FacturacionServiciosStack"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "outputs.json"
                path.write_text(json.dumps({name: {**self.outputs, "TableName": "Facturacion"}}))
                self.assertEqual(load_outputs(path)["ApiId"], "api-demo")
