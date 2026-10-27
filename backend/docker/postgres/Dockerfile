# PostGIS 16 + pgvector (busca semântica da base de conhecimento do PROMETHEUS).
# A imagem oficial do PostGIS 16 é Debian bullseye, cujo repositório PGDG foi movido para o
# arquivo (apt-archive); o pacote oficial do pgvector vem de lá, com a mesma chave de assinatura.
FROM postgis/postgis:16-3.4
RUN sed -i 's#http://apt.postgresql.org#http://apt-archive.postgresql.org#' \
        /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
