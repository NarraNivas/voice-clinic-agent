"""A local CRM sandbox for demonstrating staff handoff delivery.

This is a simulator. It is a separate small service with its own database. It is not Salesforce,
not a real CRM, and not connected to any customer system. It exists to show the HTTP contract,
idempotent upserts, retries, and recovery after failures.
"""
