from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Request bodies reject unknown fields."""

    model_config = ConfigDict(extra="forbid")
