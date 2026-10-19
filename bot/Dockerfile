FROM python:3.12-alpine
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONUNBUFFERED=1
CMD ["python3", "/bot/bot.py"]
