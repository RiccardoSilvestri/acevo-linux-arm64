FROM python:3.12-alpine
WORKDIR /app
COPY lapwatch.py schema.json /app/
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/app/lapwatch.py"]
