FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client ca-certificates \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/netdeploy
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --system --uid 10001 --create-home netdeploy \
 && mkdir -p /srv/netdeploy/data \
 && chown -R netdeploy:netdeploy /srv/netdeploy/data
USER netdeploy
EXPOSE 8787
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787", "--workers", "1"]
