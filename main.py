"""Run the Aria customer-support API locally with `uvicorn main:app --reload`."""

from api.app import app

__all__ = ["app"]
