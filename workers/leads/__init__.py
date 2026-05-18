"""Vicidial customer-prospect lead finder.

Lives alongside the job pipeline but writes to a separate `leads` table.
See `database/migrations/03_leads.sql` for schema, and `runner.py` for
the orchestrator entrypoint.
"""
