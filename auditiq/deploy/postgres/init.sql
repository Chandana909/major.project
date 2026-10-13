-- Run once, when the container creates its data directory.
-- The test database, and the role the copilot's queries run as: it can log in
-- nowhere and is granted SELECT on the copilot's tables when the schema is created.
CREATE DATABASE auditiq_test OWNER auditiq;
CREATE ROLE auditiq_reader NOLOGIN;
