-- Create migrator role
CREATE ROLE :migrator_user LOGIN PASSWORD :'migrator_password';

-- Create app role
CREATE ROLE :app_user LOGIN PASSWORD :'app_password';

-- Migrator: owns the schema, has full DDL
GRANT CONNECT ON DATABASE :app_db TO :migrator_user;
ALTER SCHEMA public OWNER TO :migrator_user;
GRANT USAGE, CREATE ON SCHEMA public TO :migrator_user;

-- App: read/write data only
GRANT CONNECT ON DATABASE :app_db TO :app_user;
GRANT USAGE ON SCHEMA public TO :app_user;

-- When migrator creates tables/sequences, app automatically gets DML rights
ALTER DEFAULT PRIVILEGES FOR ROLE :migrator_user IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :app_user;
ALTER DEFAULT PRIVILEGES FOR ROLE :migrator_user IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :app_user;
