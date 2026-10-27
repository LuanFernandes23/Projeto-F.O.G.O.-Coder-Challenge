-- Banco isolado para os testes de integração (criado apenas na primeira inicialização do volume).
CREATE DATABASE fogo_test;
\connect fogo_test
CREATE EXTENSION IF NOT EXISTS postgis;
