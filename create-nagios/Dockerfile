FROM manios/nagios:4.4.14

# Install Apache LDAP module
RUN apk add --no-cache apache2-ldap

# Copy custom Apache configuration
COPY nagios.conf /etc/apache2/conf.d/nagios.conf

# Copy custom CGI configuration
COPY cgi.cfg /tmp/cgi.cfg.custom

# Create entrypoint script to replace cgi.cfg on first run
RUN echo '#!/bin/sh' > /entrypoint-custom.sh && \
    echo 'sleep 2' >> /entrypoint-custom.sh && \
    echo 'if [ -f /opt/nagios/etc/cgi.cfg ] && [ ! -f /opt/nagios/etc/.cgi_replaced ]; then' >> /entrypoint-custom.sh && \
    echo '  cp /tmp/cgi.cfg.custom /opt/nagios/etc/cgi.cfg' >> /entrypoint-custom.sh && \
    echo '  touch /opt/nagios/etc/.cgi_replaced' >> /entrypoint-custom.sh && \
    echo 'fi' >> /entrypoint-custom.sh && \
    echo 'exec /usr/local/bin/start_nagios "$@"' >> /entrypoint-custom.sh && \
    chmod +x /entrypoint-custom.sh

ENTRYPOINT ["/entrypoint-custom.sh"]

# Expose port 80
EXPOSE 80
