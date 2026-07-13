"""
Unit tests for manifest loading and validation.
"""

import pytest
import tempfile
import os
from envelope.declaration.manifest import ManifestLoader, ModelManifest


@pytest.fixture
def valid_manifest_yaml():
    """Valid manifest YAML content."""
    return """
apiVersion: envelope.ai/v1
kind: ModelManifest
metadata:
  name: test-model
  version: v1.0.0
  description: Test model manifest
spec:
  model:
    id: llama3.1:8b
    backend: ollama
    endpoint: http://localhost:11434
    parameters:
      temperature: 0.7
      maxTokens: 1024

  tools:
    allowed:
      - search
      - lookup
    manifests:
      - tools/search.yaml
      - tools/lookup.yaml

  dataClasses:
    allowed:
      - general_inquiry
      - account_info
    taxonomy: taxonomy.yaml

  placement:
    policy: placement.yaml
    currentPlacement: on-premises

  callers:
    allowedRoles:
      - user
      - admin
"""


@pytest.fixture
def loader():
    """Create manifest loader."""
    return ManifestLoader()


class TestManifestLoading:
    """Test manifest loading from YAML."""

    def test_load_valid_manifest(self, loader, valid_manifest_yaml):
        """Valid manifest should load successfully."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(valid_manifest_yaml)
            f.flush()

            try:
                manifest = loader.load(f.name)
                assert manifest is not None
                assert manifest.metadata.name == "test-model"
                assert manifest.metadata.version == "v1.0.0"
            finally:
                os.unlink(f.name)

    def test_load_from_string(self, loader, valid_manifest_yaml):
        """Should be able to load from string."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        assert manifest.metadata.name == "test-model"
        assert manifest.spec.model.id == "llama3.1:8b"

    def test_missing_required_field(self, loader):
        """Missing required field should raise error."""
        invalid_yaml = """
apiVersion: envelope.ai/v1
kind: ModelManifest
metadata:
  name: test-model
  # missing version
spec:
  model:
    id: test
"""
        with pytest.raises(ValueError):
            loader.load_from_string(invalid_yaml)

    def test_invalid_api_version(self, loader):
        """Invalid API version should raise error."""
        invalid_yaml = """
apiVersion: envelope.ai/v2
kind: ModelManifest
metadata:
  name: test
  version: v1.0.0
spec:
  model:
    id: test
"""
        with pytest.raises(ValueError):
            loader.load_from_string(invalid_yaml)

    def test_invalid_kind(self, loader):
        """Invalid kind should raise error."""
        invalid_yaml = """
apiVersion: envelope.ai/v1
kind: InvalidKind
metadata:
  name: test
  version: v1.0.0
"""
        with pytest.raises(ValueError):
            loader.load_from_string(invalid_yaml)


class TestManifestValidation:
    """Test manifest field validation."""

    def test_valid_backend_types(self, loader, valid_manifest_yaml):
        """Valid backend types should be accepted."""
        valid_backends = ["ollama", "vllm", "openai", "anthropic"]

        for backend in valid_backends:
            yaml_content = valid_manifest_yaml.replace("backend: ollama", f"backend: {backend}")
            manifest = loader.load_from_string(yaml_content)
            assert manifest.spec.model.backend == backend

    def test_invalid_backend_type(self, loader, valid_manifest_yaml):
        """Invalid backend type should raise error."""
        yaml_content = valid_manifest_yaml.replace("backend: ollama", "backend: invalid_backend")

        with pytest.raises(ValueError):
            loader.load_from_string(yaml_content)

    def test_temperature_range(self, loader, valid_manifest_yaml):
        """Temperature must be between 0 and 2."""
        # Valid temperatures
        for temp in [0, 0.5, 1.0, 1.5, 2.0]:
            yaml_content = valid_manifest_yaml.replace("temperature: 0.7", f"temperature: {temp}")
            manifest = loader.load_from_string(yaml_content)
            assert manifest.spec.model.parameters.get("temperature") == temp

        # Invalid temperatures
        for temp in [-0.1, 2.1, 10]:
            yaml_content = valid_manifest_yaml.replace("temperature: 0.7", f"temperature: {temp}")
            with pytest.raises(ValueError):
                loader.load_from_string(yaml_content)

    def test_empty_allowed_tools(self, loader, valid_manifest_yaml):
        """Empty allowed tools list should be valid (deny-all)."""
        yaml_content = valid_manifest_yaml.replace(
            "allowed:\n      - search\n      - lookup",
            "allowed: []"
        )
        manifest = loader.load_from_string(yaml_content)
        assert manifest.spec.tools.allowed == []

    def test_empty_allowed_callers(self, loader, valid_manifest_yaml):
        """Empty allowed callers should be valid (deny-all)."""
        yaml_content = valid_manifest_yaml.replace(
            "allowedRoles:\n      - user\n      - admin",
            "allowedRoles: []"
        )
        manifest = loader.load_from_string(yaml_content)
        assert manifest.spec.callers.allowed_roles == []


class TestManifestImmutability:
    """Test that loaded manifests are immutable."""

    def test_manifest_is_frozen(self, loader, valid_manifest_yaml):
        """Manifest should be immutable after loading."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        with pytest.raises((AttributeError, TypeError)):
            manifest.metadata.name = "changed"

    def test_nested_objects_frozen(self, loader, valid_manifest_yaml):
        """Nested objects should also be immutable."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        with pytest.raises((AttributeError, TypeError)):
            manifest.spec.model.backend = "changed"


class TestManifestSerialization:
    """Test manifest serialization."""

    def test_to_dict(self, loader, valid_manifest_yaml):
        """Manifest should be serializable to dict."""
        manifest = loader.load_from_string(valid_manifest_yaml)
        data = manifest.to_dict()

        assert data["apiVersion"] == "envelope.ai/v1"
        assert data["metadata"]["name"] == "test-model"
        assert data["spec"]["model"]["id"] == "llama3.1:8b"

    def test_to_yaml(self, loader, valid_manifest_yaml):
        """Manifest should be serializable to YAML."""
        manifest = loader.load_from_string(valid_manifest_yaml)
        yaml_output = manifest.to_yaml()

        assert "apiVersion: envelope.ai/v1" in yaml_output
        assert "name: test-model" in yaml_output

    def test_round_trip(self, loader, valid_manifest_yaml):
        """Load → serialize → load should preserve content."""
        manifest1 = loader.load_from_string(valid_manifest_yaml)
        yaml_output = manifest1.to_yaml()
        manifest2 = loader.load_from_string(yaml_output)

        assert manifest1.metadata.name == manifest2.metadata.name
        assert manifest1.spec.model.id == manifest2.spec.model.id
        assert manifest1.spec.tools.allowed == manifest2.spec.tools.allowed


class TestManifestAccessors:
    """Test manifest accessor methods."""

    def test_get_allowed_tools(self, loader, valid_manifest_yaml):
        """Should return list of allowed tools."""
        manifest = loader.load_from_string(valid_manifest_yaml)
        tools = manifest.get_allowed_tools()

        assert "search" in tools
        assert "lookup" in tools
        assert len(tools) == 2

    def test_get_allowed_data_classes(self, loader, valid_manifest_yaml):
        """Should return list of allowed data classes."""
        manifest = loader.load_from_string(valid_manifest_yaml)
        classes = manifest.get_allowed_data_classes()

        assert "general_inquiry" in classes
        assert "account_info" in classes

    def test_get_model_endpoint(self, loader, valid_manifest_yaml):
        """Should return model endpoint."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        assert manifest.get_model_endpoint() == "http://localhost:11434"

    def test_is_tool_allowed(self, loader, valid_manifest_yaml):
        """Should check if tool is allowed."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        assert manifest.is_tool_allowed("search") is True
        assert manifest.is_tool_allowed("lookup") is True
        assert manifest.is_tool_allowed("delete") is False
        assert manifest.is_tool_allowed("") is False

    def test_is_caller_allowed(self, loader, valid_manifest_yaml):
        """Should check if caller role is allowed."""
        manifest = loader.load_from_string(valid_manifest_yaml)

        assert manifest.is_caller_allowed(roles=["user"]) is True
        assert manifest.is_caller_allowed(roles=["admin"]) is True
        assert manifest.is_caller_allowed(roles=["unknown"]) is False
        assert manifest.is_caller_allowed(roles=[]) is False
