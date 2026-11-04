# syntax=docker/dockerfile:1.7
# Dashboard build: the bundle is also committed, this stage just guarantees it matches the source.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx vite build --outDir /out --emptyOutDir

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 edgefeed
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
COPY --from=web /out/ src/edgefeed/static/
RUN pip install ".[postgres]" && rm -rf /root/.cache
COPY config/ config/
USER edgefeed
EXPOSE 8090 9108
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/api/scans?limit=1',timeout=4).status==200 else 1)" || exit 1
ENTRYPOINT ["edgefeed"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8090"]
