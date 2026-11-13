# Node reciente para CDK y Python 3.11, como en el proyecto del profesor.
FROM node:24-bookworm-slim AS node_runtime
FROM python:3.11-slim-bookworm

COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install --global aws-cdk@2 aws-cdk-local \
    && npm cache clean --force

WORKDIR /app
COPY app/requirements.txt /tmp/requirements.txt
COPY app/runtime-requirements.txt /tmp/runtime-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir --no-compile \
       -r /tmp/runtime-requirements.txt --target /opt/lambda-deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_EC2_METADATA_DISABLED=true

CMD ["sleep", "infinity"]
