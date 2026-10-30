ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY target_system /app/target_system
RUN useradd --uid 10001 --create-home workload
USER workload
CMD ["uvicorn", "target_system.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
