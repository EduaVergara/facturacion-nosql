"""Restaura un respaldo verificado en una tabla local existente sin sobrescribir datos."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse


def restore(client, backup):
    items = backup['items']
    keys = [(item['PK']['S'], item['SK']['S']) for item in items]
    if backup['table']['TableName'] != 'Facturacion' or backup['item_count'] != len(items) or len(keys) != len(set(keys)):
        raise RuntimeError('El respaldo no tiene tabla, cantidad o claves validas')
    table = client.describe_table(TableName='Facturacion')['Table']
    schema = {key['AttributeName']: key['KeyType'] for key in table['KeySchema']}
    indexes = {i['IndexName'] for i in table.get('GlobalSecondaryIndexes', []) if i['IndexStatus'] == 'ACTIVE'}
    if table['TableStatus'] != 'ACTIVE' or schema != {'PK': 'HASH', 'SK': 'RANGE'} or indexes != {'GSI1', 'GSI2', 'GSI3'}:
        raise RuntimeError('La tabla o sus indices no estan preparados')
    missing = []
    for item in items:
        key = {'PK': item['PK'], 'SK': item['SK']}
        current = client.get_item(TableName='Facturacion', Key=key, ConsistentRead=True).get('Item')
        if current is None:
            missing.append(item)
        elif current != item:
            raise RuntimeError('Hay un registro diferente; se detuvo antes de escribir')
    for item in missing:
        client.put_item(TableName='Facturacion', Item=item, ConditionExpression='attribute_not_exists(PK)')
    for item in items:
        key = {'PK': item['PK'], 'SK': item['SK']}
        current = client.get_item(TableName='Facturacion', Key=key, ConsistentRead=True).get('Item')
        if current != item:
            raise RuntimeError('No se pudo verificar todo el respaldo restaurado')
    return {'estado': 'ok', 'restaurados': len(missing), 'ya_identicos': len(items)-len(missing), 'verificados': len(items)}


def main():
    import boto3
    from botocore.config import Config
    endpoint = os.environ['AWS_ENDPOINT_URL']
    parsed = urlparse(endpoint)
    if parsed.scheme != 'http' or parsed.hostname not in {'emulador', 'localhost', '127.0.0.1'} or parsed.port != 4566:
        raise RuntimeError('Esta restauracion solo admite el emulador local')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, help='Ruta del respaldo de recuperar_stack.py')
    path = Path(parser.parse_args().backup)
    backup = json.loads(path.read_text(encoding='utf-8-sig'))
    client = boto3.client('dynamodb', endpoint_url=endpoint,
                          config=Config(connect_timeout=5, read_timeout=30, retries={'total_max_attempts': 1}))
    try:
        print(json.dumps(restore(client, backup), indent=2))
    finally:
        client.close()


if __name__ == '__main__':
    main()
