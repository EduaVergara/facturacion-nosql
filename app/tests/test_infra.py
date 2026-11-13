"""Comprueba la plantilla CDK; requiere las dependencias de cdk-dev."""
import importlib.util
import json
import unittest

CDK_AVAILABLE = importlib.util.find_spec("aws_cdk") is not None


@unittest.skipUnless(CDK_AVAILABLE, "Requiere aws-cdk-lib; ejecutar dentro de cdk-dev")
class InfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import aws_cdk as cdk
        from aws_cdk import assertions, aws_lambda as lambda_
        from infra.stack import FacturacionStack

        cls.app = cdk.App()
        # Solo las pruebas estructurales sustituyen el empaquetado del asset.
        stack = FacturacionStack(cls.app, "TestStack", health_code=lambda_.Code.from_inline(
            "def main(event, context): return {'statusCode': 200, 'body': '{}'}"
        ), catalog_code=lambda_.Code.from_inline(
            "def main(event, context): return {'statusCode': 200, 'body': '{}'}"
        ), invoice_code=lambda_.Code.from_inline(
            "def main(event, context): return {'statusCode': 200, 'body': '{}'}"
        ))
        imported = FacturacionStack(cls.app, "ImportedTestStack", existing_table=True,
            health_code=lambda_.Code.from_inline("def main(event, context): return {}"),
            catalog_code=lambda_.Code.from_inline("def main(event, context): return {}"),
            invoice_code=lambda_.Code.from_inline("def main(event, context): return {}"))
        cls.template = assertions.Template.from_stack(stack)
        cls.imported_template = assertions.Template.from_stack(imported)

    def test_single_table_keys_and_capacity(self):
        self.template.resource_count_is("AWS::DynamoDB::Table", 1)
        self.template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": "Facturacion", "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "PK", "KeyType": "HASH"},
                          {"AttributeName": "SK", "KeyType": "RANGE"}],
        })

    def test_indexes_project_summaries_not_full_documents(self):
        tables = self.template.find_resources("AWS::DynamoDB::Table")
        table = next(iter(tables.values()))
        indexes = table["Properties"]["GlobalSecondaryIndexes"]
        self.assertEqual({i["IndexName"] for i in indexes}, {"GSI1", "GSI2", "GSI3"})
        for index in indexes:
            name = index["IndexName"]
            self.assertEqual(index["KeySchema"], [
                {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
            ])
            self.assertEqual(index["Projection"]["ProjectionType"], "INCLUDE")
            self.assertNotIn("lineas", index["Projection"]["NonKeyAttributes"])
        self.assertEqual(table["DeletionPolicy"], "Retain")

    def test_health_route_and_local_endpoint(self):
        self.template.has_resource_properties("AWS::ApiGateway::Resource", {"PathPart": "health"})
        self.template.has_resource_properties("AWS::Lambda::Function", {
            "Handler": "handler.main", "Runtime": "python3.11",
            "Environment": {"Variables": {
                "TABLE_NAME": {"Ref": next(iter(self.template.find_resources("AWS::DynamoDB::Table")))}, "EXPECTED_INDEXES": "GSI1,GSI2,GSI3",
                "AWS_ENDPOINT_URL": "http://emulador:4566", "REDIS_HOST": "redis",
                "REDIS_PORT": "6379", "REDIS_TIMEOUT_SECONDS": "0.2", "APP_ENV": "local",
                "FRONTEND_ORIGIN": "http://localhost:8080",
            }},
        })

    def test_catalog_routes_and_python_handler(self):
        self.template.resource_count_is("AWS::Lambda::Function", 3)
        for route in ("productos", "clientes", "cajas"):
            self.template.has_resource_properties("AWS::ApiGateway::Resource", {"PathPart": route})
        self.template.has_resource_properties("AWS::Lambda::Function", {
            "Handler": "catalogo.handler.main", "Runtime": "python3.11",
        })

    def test_invoice_routes_and_handler(self):
        self.template.has_resource_properties("AWS::ApiGateway::Resource", {"PathPart": "facturas"})
        self.template.has_resource_properties("AWS::Lambda::Function", {
            "Handler": "facturacion.handler.main", "Runtime": "python3.11", "Timeout": 30,
        })
        methods = self.template.find_resources("AWS::ApiGateway::Method")
        invoice_ids = set(self.template.find_resources("AWS::ApiGateway::Resource", {"Properties": {"PathPart": "facturas"}}))
        self.assertTrue(any(m["Properties"].get("HttpMethod") == "POST" and
                            m["Properties"].get("ResourceId", {}).get("Ref") in invoice_ids
                            for m in methods.values()))

    def test_stage_not_managed_by_cloudformation(self):
        self.template.resource_count_is("AWS::ApiGateway::Stage", 0)
        self.template.resource_count_is("AWS::ApiGateway::Deployment", 1)
        deployment = next(iter(self.template.find_resources("AWS::ApiGateway::Deployment").values()))
        self.assertNotIn("StageName", deployment["Properties"])
        self.assertEqual(deployment.get("DeletionPolicy"), "Retain")
        self.assertEqual(deployment.get("UpdateReplacePolicy"), "Retain")
        methods = set(self.template.find_resources("AWS::ApiGateway::Method"))
        self.assertTrue(methods.issubset(set(deployment.get("DependsOn", []))))

    def test_recovery_reuses_table_without_creating_another(self):
        self.imported_template.resource_count_is("AWS::DynamoDB::Table", 0)
        self.imported_template.has_output("TableName", {"Value": "Facturacion"})
        functions = self.imported_template.find_resources("AWS::Lambda::Function")
        self.assertTrue(all(fn["Properties"]["Environment"]["Variables"]["TABLE_NAME"] == "Facturacion"
                            for fn in functions.values()))

    def test_invoice_role_allows_conditional_transactions(self):
        policies = self.template.find_resources("AWS::IAM::Policy")
        invoice = next(value for key, value in policies.items() if key.startswith("InvoiceHandler"))
        actions = set()
        for statement in invoice["Properties"]["PolicyDocument"]["Statement"]:
            action = statement["Action"]
            actions.update([action] if isinstance(action, str) else action)
        self.assertTrue({"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem"}.issubset(actions))
        self.assertNotIn("dynamodb:DeleteItem", actions)

    def test_product_and_invoice_handlers_receive_redis_configuration(self):
        functions = self.template.find_resources("AWS::Lambda::Function")
        for value in functions.values():
            properties = value["Properties"]
            if properties["Handler"] in {"catalogo.handler.main", "facturacion.handler.main"}:
                variables = properties["Environment"]["Variables"]
                self.assertEqual(variables["REDIS_HOST"], "redis")
                self.assertEqual(variables["REDIS_PORT"], "6379")
                self.assertEqual(variables["REDIS_TIMEOUT_SECONDS"], "0.2")

    def test_histories_have_query_permissions_on_indexes_and_three_get_routes(self):
        for template in (self.template, self.imported_template):
            policies = template.find_resources("AWS::IAM::Policy")
            invoice = next(value for key, value in policies.items() if key.startswith("InvoiceHandler"))
            statements = invoice["Properties"]["PolicyDocument"]["Statement"]
            query_statements = [s for s in statements if "dynamodb:Query" in (
                [s["Action"]] if isinstance(s["Action"],str) else s["Action"])]
            self.assertTrue(query_statements)
            self.assertTrue(any("/index/" in json.dumps(s["Resource"]) for s in query_statements))
        resources = self.template.find_resources("AWS::ApiGateway::Resource", {"Properties":{"PathPart":"facturas"}})
        self.assertEqual(len(resources),3)
        methods = self.template.find_resources("AWS::ApiGateway::Method")
        get_parents = {m["Properties"].get("ResourceId",{}).get("Ref") for m in methods.values()
                       if m["Properties"]["HttpMethod"] == "GET"}
        self.assertTrue(set(resources).issubset(get_parents))
