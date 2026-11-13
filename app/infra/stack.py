"""Tabla única, tres GSI, diagnóstico y API de catálogo."""
import os
import hashlib
import shutil
from pathlib import Path

import aws_cdk as cdk
import jsii
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_dynamodb as ddb
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_iam as iam
from constructs import Construct

from infra.schema import INDEX_PROJECTIONS, TABLE_NAME

APP_DIR = Path(__file__).resolve().parents[1]


@jsii.implements(cdk.ILocalBundling)
class RuntimeBundle:
    """Copia código y librerías Linux preparadas durante docker build.

    El empaquetado sigue el enfoque del profesor para LocalStack: incluye
    dependencias en el zip de la función, sin depender de Lambda Layers.
    """

    def __init__(self, source: Path):
        self.source = source

    def try_bundle(self, output_dir: str, options) -> bool:
        dependencies = Path(os.environ.get("LAMBDA_DEPENDENCIES_DIR", "/opt/lambda-deps"))
        if not (dependencies / "redis").is_dir() or not (dependencies / "boto3").is_dir():
            raise RuntimeError("Faltan dependencias de Lambda; reconstruye el contenedor cdk-dev.")
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "bin")
        shutil.copytree(dependencies, output_dir, dirs_exist_ok=True, ignore=ignore)
        shutil.copytree(self.source, output_dir, dirs_exist_ok=True, ignore=ignore)
        return True


class FacturacionStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, health_code=None, catalog_code=None, invoice_code=None, existing_table=False, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        if existing_table:
            table = ddb.Table.from_table_attributes(
                self, "FacturacionExistingTable", table_name=TABLE_NAME,
                global_indexes=list(INDEX_PROJECTIONS),
            )
        else:
            table = ddb.Table(
                self, "FacturacionTable",
                table_name=TABLE_NAME,
                partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
                sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
                billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
                removal_policy=cdk.RemovalPolicy.RETAIN,
            )
            for name, projection in INDEX_PROJECTIONS.items():
                table.add_global_secondary_index(
                    index_name=name,
                    partition_key=ddb.Attribute(name=f"{name}PK", type=ddb.AttributeType.STRING),
                    sort_key=ddb.Attribute(name=f"{name}SK", type=ddb.AttributeType.STRING),
                    projection_type=ddb.ProjectionType.INCLUDE,
                    non_key_attributes=projection,
                )

        def bundle(source):
            return lambda_.Code.from_asset(
                str(source),
                asset_hash_type=cdk.AssetHashType.OUTPUT,
                bundling=cdk.BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=["bash", "-c", "exit 1"],
                    local=RuntimeBundle(source),
                ),
            )

        if health_code is None:
            health_code = bundle(APP_DIR / "lambdas" / "health")

        health = lambda_.Function(
            self, "HealthHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.X86_64,
            handler="handler.main",
            code=health_code,
            timeout=cdk.Duration.seconds(5),
            memory_size=256,
            environment={
                "TABLE_NAME": table.table_name,
                "EXPECTED_INDEXES": ",".join(INDEX_PROJECTIONS),
                "AWS_ENDPOINT_URL": "http://emulador:4566",
                "REDIS_HOST": "redis",
                "REDIS_PORT": "6379",
                "REDIS_TIMEOUT_SECONDS": "0.2",
                "APP_ENV": "local",
            },
        )
        table.grant(health, "dynamodb:DescribeTable")

        origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:8080")
        api = apigw.RestApi(
            self, "FacturacionApi",
            rest_api_name="Facturacion-Local",
            description="Catalogo del proyecto de facturacion NoSQL",
            deploy=False,
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=[origin],
                allow_methods=["GET", "POST", "PUT", "OPTIONS"],
                allow_headers=["Content-Type"],
            ),
        )
        resource = api.root.add_resource("health")
        resource.add_method("GET", apigw.LambdaIntegration(health))

        catalog = lambda_.Function(
            self, "CatalogHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.X86_64,
            handler="catalogo.handler.main",
            code=catalog_code if catalog_code is not None else bundle(APP_DIR / "lambdas"),
            timeout=cdk.Duration.seconds(10), memory_size=256,
            environment={
                "TABLE_NAME": table.table_name,
                "AWS_ENDPOINT_URL": "http://emulador:4566",
                "FRONTEND_ORIGIN": origin, "APP_ENV": "local",
                "REDIS_HOST": "redis", "REDIS_PORT": "6379", "REDIS_TIMEOUT_SECONDS": "0.2",
            },
        )
        table.grant_read_write_data(catalog)
        integration = apigw.LambdaIntegration(catalog)
        catalog_items = {}
        for name in ("productos", "clientes"):
            collection = api.root.add_resource(name)
            collection.add_method("GET", integration)
            collection.add_method("POST", integration)
            item = collection.add_resource("{id}")
            catalog_items[name] = item
            item.add_method("GET", integration)
            item.add_method("PUT", integration)
        boxes_collection = api.root.add_resource("cajas")
        boxes_collection.add_method("GET", integration)

        invoices = lambda_.Function(
            self, "InvoiceHandler", runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.X86_64, handler="facturacion.handler.main",
            code=invoice_code if invoice_code is not None else bundle(APP_DIR / "lambdas"),
            timeout=cdk.Duration.seconds(30), memory_size=256,
            environment={"TABLE_NAME": table.table_name, "AWS_ENDPOINT_URL": "http://emulador:4566",
                         "FRONTEND_ORIGIN": origin, "APP_ENV": "local",
                         "REDIS_HOST": "redis", "REDIS_PORT": "6379", "REDIS_TIMEOUT_SECONDS": "0.2"},
        )
        table.grant(invoices, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:ConditionCheckItem")
        invoices.add_to_role_policy(iam.PolicyStatement(actions=["dynamodb:Query"],
            resources=[table.table_arn, *[f"{table.table_arn}/index/{name}" for name in INDEX_PROJECTIONS]]))
        invoice_integration = apigw.LambdaIntegration(invoices)
        invoice_collection = api.root.add_resource("facturas")
        invoice_collection.add_method("POST", invoice_integration)
        invoice_collection.add_method("GET", invoice_integration)
        invoice_collection.add_resource("{id}").add_method("GET", invoice_integration)
        catalog_items["clientes"].add_resource("facturas").add_method("GET", invoice_integration)
        boxes_collection.add_resource("{id}").add_resource("facturas").add_method("GET", invoice_integration)

        # LocalStack 4.14 no actualiza correctamente AWS::ApiGateway::Stage.
        # CDK conserva la API y su snapshot; publicar_api.py asocia prod por SDK.
        deployment = apigw.Deployment(self, "ApiDeployment", api=api, retain_deployments=True)
        deployment.add_to_logical_id({
            "infra_source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "origin": origin,
        })
        for node in api.node.find_all():
            if isinstance(node, apigw.Method):
                deployment.node.add_dependency(node)
        api_url = f"http://{api.rest_api_id}.execute-api.localhost.localstack.cloud:4566/prod/"

        # El handler y el preflight usan el mismo origen concreto.
        health.add_environment("FRONTEND_ORIGIN", origin)
        cdk.CfnOutput(self, "ApiId", value=api.rest_api_id)
        cdk.CfnOutput(self, "ApiUrl", value=api_url)
        cdk.CfnOutput(self, "HealthUrl", value=f"{api_url}health")
        cdk.CfnOutput(self, "ApiDeploymentId", value=deployment.deployment_id)
        cdk.CfnOutput(self, "StageName", value="prod")
        cdk.CfnOutput(self, "ActiveStackName", value=self.stack_name)
        cdk.CfnOutput(self, "TableName", value=table.table_name)
