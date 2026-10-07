FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data

WORKDIR /app
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -f /run/secrets/build_ca_bundle ]; then \
        export PIP_CERT=/run/secrets/build_ca_bundle; \
    fi; \
    pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY config ./config
RUN --mount=type=secret,id=build_ca_bundle \
    if [ -f /run/secrets/build_ca_bundle ]; then \
        export SSL_CERT_FILE=/run/secrets/build_ca_bundle UV_SYSTEM_CERTS=true; \
    fi; \
    uv sync --locked --no-dev --no-editable \
    && chmod -R a+rX /app/config \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /data/documents /data/reports \
    && chown -R app:app /data

USER app
EXPOSE 8000
ENTRYPOINT ["motorsport-research"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
