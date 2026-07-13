"""
FastAPI Application

Main application entry point with all envelope enforcement.
"""

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from envelope.declaration.manifest import ModelManifest, ManifestLoader
from envelope.declaration.tools import ToolRegistry
from envelope.declaration.taxonomy import DataClassTaxonomy
from envelope.declaration.placement import PlacementPolicy
from envelope.runtime.contract import RuntimeContract
from envelope.runtime.lifecycle import LifecycleManager
from envelope.enforcement.ingress import IngressGate
from envelope.enforcement.tool_gate import ToolGate
from envelope.enforcement.egress import EgressGate
from envelope.enforcement.escalation import EscalationEnforcer
from envelope.enforcement.key_broker import KeyBroker
from envelope.record.provenance import ProvenanceStore, InMemoryProvenanceStore
from envelope.record.hashchain import HashChain
from envelope.record.encryption import PerSubjectEncryption
from envelope.handoff.reference_sink import ReferenceSink


class EnvelopeAPI:
    """
    Main API class that ties together all envelope components.

    This is the central orchestrator for model inference with
    all enforcement gates and record keeping.
    """

    def __init__(
        self,
        manifest: ModelManifest,
        runtime: RuntimeContract | None = None,
    ):
        self.manifest = manifest

        # Core registries
        self.tool_registry = ToolRegistry()
        self.taxonomy = DataClassTaxonomy()
        self.placement_policy = PlacementPolicy()

        # Runtime
        self.runtime = runtime
        self.lifecycle = LifecycleManager()

        # Record system
        self.provenance_store: ProvenanceStore = InMemoryProvenanceStore()
        self.encryption = PerSubjectEncryption()
        self.hashchain: HashChain | None = None

        # Enforcement gates
        self.ingress_gate = IngressGate(manifest, self.taxonomy)
        self.tool_gate = ToolGate(manifest, self.tool_registry)
        self.egress_gate = EgressGate(manifest, self.taxonomy)
        self.escalation_enforcer = EscalationEnforcer(manifest)
        self.key_broker = KeyBroker(
            manifest, self.taxonomy, self.placement_policy, self.encryption
        )

        # Handoff
        self.escalation_sink = ReferenceSink()

    async def initialize(self) -> None:
        """Initialize all components."""
        self.hashchain = HashChain(self.provenance_store)
        await self.hashchain.initialize()

        if self.runtime:
            await self.lifecycle.start_loading()
            await self.runtime.load()
            await self.lifecycle.complete_loading()

    async def shutdown(self) -> None:
        """Shutdown all components."""
        if self.runtime:
            await self.lifecycle.stop()
            await self.runtime.unload()


def create_app(
    manifest: ModelManifest | None = None,
    runtime: RuntimeContract | None = None,
    title: str = "Model Deployment Envelope",
    version: str = "0.1.0",
) -> FastAPI:
    """
    Create the FastAPI application.

    Args:
        manifest: Optional manifest (can be loaded later)
        runtime: Optional runtime backend
        title: API title
        version: API version
    """
    api_state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Application lifespan handler."""
        if manifest and runtime:
            envelope = EnvelopeAPI(manifest, runtime)
            await envelope.initialize()
            api_state["envelope"] = envelope

        yield

        if "envelope" in api_state:
            await api_state["envelope"].shutdown()

    app = FastAPI(
        title=title,
        version=version,
        description="Model Deployment Envelope API with platform-enforced boundaries",
        lifespan=lifespan,
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store state accessor
    @app.middleware("http")
    async def inject_state(request: Request, call_next):
        request.state.envelope = api_state.get("envelope")
        response = await call_next(request)
        return response

    # Import and include routers
    from envelope.api.routes.inference import router as inference_router
    from envelope.api.routes.admin import router as admin_router
    from envelope.api.routes.verification import router as verification_router

    app.include_router(inference_router, prefix="/v1", tags=["inference"])
    app.include_router(admin_router, prefix="/admin", tags=["admin"])
    app.include_router(verification_router, prefix="/verify", tags=["verification"])

    @app.get("/")
    async def root():
        return {
            "name": title,
            "version": version,
            "status": "running",
        }

    @app.get("/health")
    async def health():
        envelope = api_state.get("envelope")
        if envelope and envelope.runtime:
            runtime_healthy = await envelope.runtime.health()
            lifecycle_healthy = envelope.lifecycle.state_machine.is_healthy()
            return {
                "healthy": runtime_healthy and lifecycle_healthy,
                "runtime": runtime_healthy,
                "lifecycle": envelope.lifecycle.state_machine.state.name,
            }
        return {"healthy": True, "runtime": None}

    return app
