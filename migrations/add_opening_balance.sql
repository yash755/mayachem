-- Migration: Add opening_balance to client table
-- Date: 2026-03-11

-- For SQLite
ALTER TABLE client ADD COLUMN opening_balance FLOAT NOT NULL DEFAULT 0.0;
