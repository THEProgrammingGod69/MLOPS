# Prometheus for the Render Blueprint (render.yaml). Build context: repository root.
FROM prom/prometheus:v2.53.2
COPY monitoring/prometheus/alerts.yml /etc/prometheus/alerts.yml
COPY deploy/render/prometheus.yml.template /etc/prometheus/prometheus.yml.template
COPY deploy/render/prometheus-entrypoint.sh /etc/prometheus/entrypoint.sh
EXPOSE 9090
ENTRYPOINT ["/bin/sh", "/etc/prometheus/entrypoint.sh"]
