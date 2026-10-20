FROM python:3.12-slim

RUN pip install uv --no-cache-dir

WORKDIR /app
COPY pyproject.toml .
RUN uv pip install --system .

COPY src/ src/

CMD ["python", "-m", "forwarder"]
