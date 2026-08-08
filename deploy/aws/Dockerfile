ARG GRAPH_HOPPER_IMAGE=israelhikingmap/graphhopper:11.0
FROM ${GRAPH_HOPPER_IMAGE} AS graphhopper

FROM public.ecr.aws/awsguru/aws-lambda-adapter:1.0.0 AS lambda-adapter

FROM python:3.12-slim-bookworm

ARG REGION_SLUG=vlaanderen
ENV JAVA_HOME=/opt/java/openjdk \
    PATH="/opt/java/openjdk/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AWS_LWA_PORT=8080 \
    AWS_LWA_INVOKE_MODE=response_stream \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    AWS_LWA_ASYNC_INIT=true \
    LUSMAKER_STATIC_HOME=/opt/lusmaker \
    LUSMAKER_REGION=${REGION_SLUG}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends bash ca-certificates curl libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=graphhopper /opt/java/openjdk /opt/java/openjdk
COPY --from=graphhopper /graphhopper /opt/graphhopper
COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter

WORKDIR /app
COPY pyproject.toml ./
COPY lusmaker ./lusmaker
RUN pip install --no-cache-dir '.[aws]'

COPY .aws/region/ /opt/lusmaker/
COPY deploy/aws/entrypoint.sh /app/deploy/aws/entrypoint.sh
RUN chmod 0555 /app/deploy/aws/entrypoint.sh \
    && test -f "/opt/lusmaker/regions/${REGION_SLUG}/gh/config.yml" \
    && test -d "/opt/lusmaker/regions/${REGION_SLUG}/gh/graph-cache" \
    && ln -s "/opt/lusmaker/regions/${REGION_SLUG}" /lus

EXPOSE 8080
ENTRYPOINT ["/app/deploy/aws/entrypoint.sh"]
