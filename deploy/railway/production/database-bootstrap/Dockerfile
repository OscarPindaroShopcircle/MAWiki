FROM postgres:18.3

COPY deploy/railway/production/database-bootstrap/bootstrap.sh /app/bootstrap.sh
COPY deploy/railway/production/database-bootstrap/bootstrap.sql /app/bootstrap.sql

RUN chmod +x /app/bootstrap.sh

CMD ["/app/bootstrap.sh"]
