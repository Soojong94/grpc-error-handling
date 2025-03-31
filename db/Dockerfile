FROM postgres:13-alpine

COPY init.sql /docker-entrypoint-initdb.d/

ENV POSTGRES_USER=testuser
ENV POSTGRES_PASSWORD=testpassword
ENV POSTGRES_DB=testdb

EXPOSE 5432