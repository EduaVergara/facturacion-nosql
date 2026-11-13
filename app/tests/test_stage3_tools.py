"""Preparacion conservadora de actualizaciones y reintentos HTTP acotados."""
import copy
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local_http import request_json
from preparar_etapa3 import protect_deployments


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.template = {"Resources": {
            "Api": {"Type": "AWS::ApiGateway::RestApi", "Properties": {"Name": "Demo"}},
            "DeploymentOld": {"Type": "AWS::ApiGateway::Deployment", "Properties": {"RestApiId": {"Ref": "Api"}}}}}
        self.client = Mock(spec=["describe_stacks", "get_template", "update_stack"])
        self.client.describe_stacks.side_effect = [
            {"Stacks": [{"StackStatus": "CREATE_COMPLETE", "Parameters": [{"ParameterKey": "BootstrapVersion"}]}]},
            {"Stacks": [{"StackStatus": "UPDATE_COMPLETE"}]}]
        self.saved = copy.deepcopy(self.template)
        self.saved["Resources"]["DeploymentOld"].update(DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
        self.client.get_template.side_effect = [{"TemplateBody": self.template}, {"TemplateBody": self.saved}]

    def test_preparation_changes_only_deployment_retention_policies(self):
        report = protect_deployments(self.client, "FacturacionServiciosStack", sleep=Mock())
        submitted = json.loads(self.client.update_stack.call_args.kwargs["TemplateBody"])
        self.assertEqual(submitted, self.saved)
        self.assertEqual(report["deployments_protegidos"], 1)
        self.assertEqual(self.client.update_stack.call_args.kwargs["Parameters"],
                         [{"ParameterKey": "BootstrapVersion", "UsePreviousValue": True}])

    def test_already_protected_template_needs_no_update(self):
        self.client.get_template.side_effect = None
        self.client.get_template.return_value = {"TemplateBody": json.dumps(self.saved)}
        self.assertEqual(protect_deployments(self.client, "FacturacionServiciosStack")["actualizacion"], "innecesaria")
        self.client.update_stack.assert_not_called()

    def test_unstable_stack_stops_before_update(self):
        self.client.describe_stacks.side_effect = None
        self.client.describe_stacks.return_value = {"Stacks": [{"StackStatus": "UPDATE_IN_PROGRESS"}]}
        with self.assertRaises(RuntimeError):
            protect_deployments(self.client, "FacturacionServiciosStack")
        self.client.update_stack.assert_not_called()

    def test_failed_protection_stops_before_main_deploy(self):
        self.client.describe_stacks.side_effect = [
            {"Stacks": [{"StackStatus": "CREATE_COMPLETE"}]},
            {"Stacks": [{"StackStatus": "UPDATE_ROLLBACK_COMPLETE"}]}]
        with self.assertRaises(RuntimeError):
            protect_deployments(self.client, "FacturacionServiciosStack", sleep=Mock())


class LocalHttpTests(unittest.TestCase):
    def reply(self, status=200, body=None):
        response = Mock()
        response.status = status
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps(body or {"estado": "ok"}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_timeout_retries_identical_invoice_body(self):
        data = {"solicitud_id": "same-key", "lineas": []}
        with patch("local_http.urllib.request.urlopen", side_effect=[TimeoutError(), self.reply()]) as send, \
             patch("local_http.time.sleep"):
            request_json("http://emulador:4566/facturas", method="POST", data=data)
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0].args[0].data, send.call_args_list[1].args[0].data)

    def test_business_conflict_does_not_retry(self):
        error = urllib.error.HTTPError("http://emulador", 409, "Conflict", {}, io.BytesIO(b'{"error":"version"}'))
        with patch("local_http.urllib.request.urlopen", side_effect=error) as send:
            status, payload, _ = request_json("http://emulador", expected=(409,))
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "version")
        self.assertEqual(send.call_count, 1)

    def test_exhausted_timeouts_do_not_report_success(self):
        with patch("local_http.urllib.request.urlopen", side_effect=TimeoutError()) as send, patch("local_http.time.sleep"):
            with self.assertRaises(RuntimeError):
                request_json("http://emulador", attempts=2)
        self.assertEqual(send.call_count, 2)
