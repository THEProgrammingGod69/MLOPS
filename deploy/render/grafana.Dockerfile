# Grafana for the Render Blueprint (render.yaml). Build context: repository root.
FROM grafana/grafana:11.2.2
COPY monitoring/grafana/provisioning/dashboards /etc/grafana/provisioning/dashboards
COPY monitoring/grafana/provisioning/alerting /etc/grafana/provisioning/alerting
COPY monitoring/grafana/provisioning/plugins /etc/grafana/provisioning/plugins
COPY deploy/render/grafana-datasource.yml /etc/grafana/provisioning/datasources/prometheus.yml
COPY monitoring/grafana/dashboards /var/lib/grafana/dashboards
ENV GF_AUTH_ANONYMOUS_ENABLED=true \
    GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer \
    GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/prediction_dashboard.json \
    GF_USERS_DEFAULT_THEME=dark \
    GF_USERS_ALLOW_SIGN_UP=false \
    GF_ANALYTICS_REPORTING_ENABLED=false \
    GF_ANALYTICS_CHECK_FOR_UPDATES=false \
    GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false \
    GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED=true \
    GF_NEWS_NEWS_FEED_ENABLED=false
EXPOSE 3000
