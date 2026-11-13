"""Respalda datos y conserva el deployment al que todavia apunta prod."""
import copy
import json
import os
import sys
import time
from pathlib import Path

from publicar_api import check_local_endpoint
from recuperar_stack import prepare


def protect_deployments(client, stack_name, *, sleep=time.sleep, max_polls=60):
    stack = client.describe_stacks(StackName=stack_name)["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
        raise RuntimeError("El stack de servicios no esta listo para actualizar")
    template = client.get_template(StackName=stack_name)["TemplateBody"]
    template = json.loads(template) if isinstance(template, str) else template
    updated = copy.deepcopy(template)
    count = 0
    for resource in updated["Resources"].values():
        if resource["Type"] == "AWS::ApiGateway::Deployment":
            if resource.get("DeletionPolicy") != "Retain" or resource.get("UpdateReplacePolicy") != "Retain":
                resource.update(DeletionPolicy="Retain", UpdateReplacePolicy="Retain")
                count += 1
    if not count:
        return {"deployments_protegidos": 0, "actualizacion": "innecesaria"}
    print("Conservando el deployment anterior antes de actualizar la API...", flush=True)
    parameters = [{"ParameterKey": p["ParameterKey"], "UsePreviousValue": True}
                  for p in stack.get("Parameters", [])]
    client.update_stack(StackName=stack_name, TemplateBody=json.dumps(updated),
                        Parameters=parameters, Capabilities=["CAPABILITY_NAMED_IAM"])
    for _ in range(max_polls):
        current = client.describe_stacks(StackName=stack_name)["Stacks"][0]["StackStatus"]
        if current == "UPDATE_COMPLETE":
            saved = client.get_template(StackName=stack_name)["TemplateBody"]
            saved = json.loads(saved) if isinstance(saved, str) else saved
            for resource in saved["Resources"].values():
                if resource["Type"] == "AWS::ApiGateway::Deployment" and (
                    resource.get("DeletionPolicy") != "Retain" or resource.get("UpdateReplacePolicy") != "Retain"):
                    raise RuntimeError("No se confirmo la conservacion del deployment anterior")
            return {"deployments_protegidos": count, "actualizacion": "completada"}
        if current not in {"UPDATE_IN_PROGRESS", "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"}:
            raise RuntimeError(f"No se pudo conservar el deployment anterior: {current}")
        sleep(2)
    raise RuntimeError("La preparacion sigue en curso; espera su finalizacion antes de desplegar")


if __name__ == "__main__":
    try:
        import boto3
        check_local_endpoint(os.environ.get("AWS_ENDPOINT_URL", ""))
        directory = Path(__file__).resolve().parents[1]
        cf = boto3.client("cloudformation")
        report = prepare(directory, boto3.client("dynamodb"), cf, os.environ["AWS_ENDPOINT_URL"])
        previous_template = cf.get_template(StackName=report["stack_servicios"])["TemplateBody"]
        (Path(report["respaldo"]).parent / "stack-template-anterior.json").write_text(
            json.dumps(previous_template, ensure_ascii=False, indent=2), encoding="utf-8")
        report.update(protect_deployments(cf, report["stack_servicios"]))
        print(json.dumps(report, indent=2, ensure_ascii=False))
    except Exception as exc:
        print(f"No se pudo preparar la etapa 3: {exc}", file=sys.stderr)
        sys.exit(1)
