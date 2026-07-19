"""JSON Schema for the broker wire contract.

Assembles the pydantic wire models into a single, deterministic dict keyed by
model name. The shim's future ``json-schema-control`` command invokes this (via
the ``emit-schema`` CLI command) to publish the contract the host side must
honour, so the output is stable (sorted) to keep a checked-in diff meaningful.
"""

from __future__ import annotations

from typing import Any

from .models import WireInventory, WireRepo

# The models that make up the wire contract, keyed by the name they appear under.
_WIRE_MODELS = (WireRepo, WireInventory)


def emit_schema() -> dict[str, Any]:
    """Return the JSON Schema for every wire model, keyed by model name.

    Deterministic: models are emitted in a fixed order and each schema is built
    by pydantic's ``model_json_schema``. Callers that want byte-stable text
    should ``json.dumps(..., sort_keys=True)``.
    """
    return {model.__name__: model.model_json_schema() for model in _WIRE_MODELS}
