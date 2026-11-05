ARG PYTHON_IMAGE=python:3.13-slim@sha256:ae14d4ce8771606477a81446e7ef429edd6762305fc50c84507c1041fa8285d1
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build
COPY connector/pyproject.toml ./pyproject.toml
COPY requirements.lock ./constraints.txt
COPY src/airlock_contracts ./src/airlock_contracts
COPY src/airlock_connector ./src/airlock_connector
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10001 --create-home connector && mkdir /data && chown connector:connector /data
USER 10001:10001
WORKDIR /data
EXPOSE 8742
ENTRYPOINT ["airlock-connector"]
CMD ["serve", "--directory", "/data", "--host", "0.0.0.0"]
