-- Runs once on first start of the postgres container (research R5, task T007).
-- One instance, two databases: the app's and Langfuse's metadata database.
CREATE DATABASE codecompass;
CREATE DATABASE langfuse;

\connect codecompass
CREATE EXTENSION IF NOT EXISTS vector;
