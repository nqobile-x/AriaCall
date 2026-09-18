"""Run the Aria customer-support API locally with `uvicorn main:app --reload`."""

import logging

logging.basicConfig(level=logging.INFO)

from api.app import app

__all__ = ["app"]
