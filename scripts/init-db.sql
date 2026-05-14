-- CitedBy platform database initialisation
-- Creates extensions, roles, and database-level config

-- Extensions (must run as superuser)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Application role (limited privileges; app connects as this role)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'citedby_app') THEN
    CREATE ROLE citedby_app LOGIN PASSWORD 'localpassword';
  END IF;
END$$;

-- Grant schema privileges
GRANT CONNECT ON DATABASE citedby TO citedby_app;
GRANT USAGE ON SCHEMA public TO citedby_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO citedby_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO citedby_app;

-- Public audit role (restricted; used by free-audit public endpoints only)
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'citedby_public_audit') THEN
    CREATE ROLE citedby_public_audit LOGIN PASSWORD 'publicauditpassword';
  END IF;
END$$;

GRANT CONNECT ON DATABASE citedby TO citedby_public_audit;
GRANT USAGE ON SCHEMA public TO citedby_public_audit;
