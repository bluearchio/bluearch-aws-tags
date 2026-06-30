-- PostgreSQL initialization script for Tag Manager CLI
-- This script runs automatically when the PostgreSQL container starts

-- Create the tag_manager database (if it doesn't already exist)
-- Note: The database is already created by POSTGRES_DB environment variable
-- but we include this for completeness

-- Create any additional schemas or configurations here if needed
-- The main database schema will be created by Alembic migrations

-- Set up any database-level configurations
-- Enable necessary extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Log successful initialization
SELECT 'Tag Manager CLI PostgreSQL database initialized successfully' AS status;
