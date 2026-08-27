"""Namespace for the async report application boundary.

The repository is also kept under ``app/db`` to match the migration contract;
this distinct import name avoids colliding with the legacy Railway Flask
module, which is imported as top-level ``app`` by older runtime tests.
"""
