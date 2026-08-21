SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'migrator_user', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_user');
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'migrator_user', :'migrator_password');
\gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user');
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password');
\gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'openwebui_user', :'openwebui_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'openwebui_user');
\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'openwebui_user', :'openwebui_password');
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'openwebui_db', :'openwebui_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'openwebui_db');
\gexec

GRANT CONNECT ON DATABASE :"app_db" TO :"migrator_user";
ALTER SCHEMA public OWNER TO :"migrator_user";
GRANT USAGE, CREATE ON SCHEMA public TO :"migrator_user";
GRANT CONNECT ON DATABASE :"app_db" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migrator_user" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app_user";
