import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


Coordinate = Annotated[float, Field(ge=-50, le=50)]


class SceneObject(StrictModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(default="Object", min_length=1, max_length=40)
    shape: Literal["cube", "sphere", "cylinder"] = "cube"
    size: float = Field(default=2, ge=0.1, le=20)
    position: tuple[Coordinate, Coordinate, Coordinate] = (0, 0, 0)
    color: str = Field(default="#77caba", pattern=r"^#[a-fA-F0-9]{6}$")


class SceneSpec(StrictModel):
    schema_version: Literal[1] = 1
    objects: list[SceneObject] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({obj.id for obj in self.objects}) != len(self.objects):
            raise ValueError("Object IDs must be unique")
        return self


class ProjectCreate(StrictModel):
    name: str = Field(default="Nouveau projet", min_length=1, max_length=80)
    scene: SceneSpec = Field(default_factory=SceneSpec)


class ProjectOrigin(StrictModel):
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision: int = Field(ge=1)


class PortableProject(StrictModel):
    format: Literal["blender-cloud-agent/project"] = "blender-cloud-agent/project"
    format_version: Literal[1] = 1
    project: ProjectCreate
    source: ProjectOrigin | None = None


class ProjectEdit(StrictModel):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=80)
    scene: SceneSpec


class RenderRequest(StrictModel):
    revision: int = Field(ge=1)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=2000)
    revision: int | None = Field(default=None, ge=1)
    object_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @model_validator(mode="after")
    def selection_requires_revision(self):
        if self.object_id and self.revision is None:
            raise ValueError("An object selection requires the displayed project revision")
        return self


class RestoreRequest(StrictModel):
    revision: int = Field(ge=1)
    source_revision: int = Field(ge=1)


class VersionSummary(StrictModel):
    project_id: str
    revision: int
    name: str
    object_count: int
    saved_at: float
    reason: Literal["created", "edited", "confirmed", "restored", "migration"]
    restored_from: int | None


class VersionView(VersionSummary):
    scene: SceneSpec


class Login(StrictModel):
    token: str = Field(min_length=1, max_length=256)


class AgentPlan(StrictModel):
    summary: str = Field(min_length=1, max_length=500)
    scene: SceneSpec | None = None


class ProjectView(ProjectCreate):
    id: str
    revision: int
    created_at: float
    updated_at: float


class ArtifactView(StrictModel):
    bytes: int
    sha256: str
    blender_version: str


class JobView(StrictModel):
    id: str
    project_id: str
    revision: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    error_code: str | None
    created_at: float
    updated_at: float
    scene: SceneSpec
    files: dict[str, str]
    artifacts: dict[str, ArtifactView]


class ProposalView(AgentPlan):
    id: str
    project_id: str
    base_revision: int
    message: str
    mode: Literal["rules", "llm"]
    job_id: str | None
    created_at: float
    supported: bool
