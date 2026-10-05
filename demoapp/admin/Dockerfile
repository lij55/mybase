FROM python:3.14.8-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_KIND=admin PORT=8080
COPY admin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY common/server.py /app/server.py
COPY common/common.js common/style.css /app/static/
COPY admin/static/index.html /app/static/index.html
COPY admin/static/app.js /app/static/app.js
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/server.py"]
