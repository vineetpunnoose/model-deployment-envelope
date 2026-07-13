"""
Unit tests for hash chain integrity verification.
"""

import pytest
from envelope.record.hashchain import HashChain, ChainEntry


@pytest.fixture
def hash_chain():
    """Create a fresh hash chain."""
    return HashChain()


class TestHashChainBasics:
    """Basic hash chain functionality."""

    def test_empty_chain(self, hash_chain):
        """Empty chain should have no entries."""
        assert len(hash_chain) == 0
        assert hash_chain.verify() is True  # Empty chain is valid

    def test_add_entry(self, hash_chain):
        """Adding entry should increase chain length."""
        hash_chain.append({"data": "test"})
        assert len(hash_chain) == 1

    def test_first_entry_has_no_previous(self, hash_chain):
        """First entry should have null previous hash."""
        hash_chain.append({"data": "first"})
        entry = hash_chain.get(0)
        assert entry.prev_hash is None or entry.prev_hash == ""

    def test_second_entry_links_to_first(self, hash_chain):
        """Second entry should reference first entry's hash."""
        hash_chain.append({"data": "first"})
        hash_chain.append({"data": "second"})

        first = hash_chain.get(0)
        second = hash_chain.get(1)

        assert second.prev_hash == first.hash

    def test_chain_link_integrity(self, hash_chain):
        """Each entry should correctly link to previous."""
        for i in range(10):
            hash_chain.append({"data": f"entry-{i}"})

        for i in range(1, 10):
            current = hash_chain.get(i)
            previous = hash_chain.get(i - 1)
            assert current.prev_hash == previous.hash


class TestHashChainVerification:
    """Hash chain verification tests."""

    def test_valid_chain_verifies(self, hash_chain):
        """Valid chain should pass verification."""
        for i in range(5):
            hash_chain.append({"data": f"entry-{i}"})

        assert hash_chain.verify() is True

    def test_tampered_content_detected(self, hash_chain):
        """Tampering with content should be detected."""
        hash_chain.append({"data": "original"})
        hash_chain.append({"data": "second"})

        # Tamper with first entry's content
        hash_chain._entries[0].content = {"data": "tampered"}

        assert hash_chain.verify() is False

    def test_tampered_hash_detected(self, hash_chain):
        """Tampering with hash should be detected."""
        hash_chain.append({"data": "first"})
        hash_chain.append({"data": "second"})

        # Tamper with hash
        hash_chain._entries[0].hash = "fake_hash_value"

        assert hash_chain.verify() is False

    def test_broken_link_detected(self, hash_chain):
        """Breaking prev_hash link should be detected."""
        hash_chain.append({"data": "first"})
        hash_chain.append({"data": "second"})
        hash_chain.append({"data": "third"})

        # Break link
        hash_chain._entries[1].prev_hash = "wrong_hash"

        assert hash_chain.verify() is False

    def test_verify_returns_break_location(self, hash_chain):
        """Verification should return where chain breaks."""
        for i in range(5):
            hash_chain.append({"data": f"entry-{i}"})

        # Tamper with entry 3
        hash_chain._entries[2].content = {"data": "tampered"}

        is_valid, break_index = hash_chain.verify_detailed()

        assert is_valid is False
        assert break_index == 2


class TestHashChainAlgorithm:
    """Test hash algorithm properties."""

    def test_hash_is_deterministic(self, hash_chain):
        """Same content should produce same hash."""
        content = {"data": "test", "value": 123}

        hash1 = hash_chain._compute_hash(content, "")
        hash2 = hash_chain._compute_hash(content, "")

        assert hash1 == hash2

    def test_hash_includes_prev_hash(self, hash_chain):
        """Hash should incorporate previous hash."""
        content = {"data": "test"}

        hash1 = hash_chain._compute_hash(content, "prev_a")
        hash2 = hash_chain._compute_hash(content, "prev_b")

        assert hash1 != hash2

    def test_hash_length(self, hash_chain):
        """Hash should be SHA-256 (64 hex chars)."""
        hash_chain.append({"data": "test"})
        entry = hash_chain.get(0)

        assert len(entry.hash) == 64
        assert all(c in "0123456789abcdef" for c in entry.hash)

    def test_small_change_different_hash(self, hash_chain):
        """Small content changes should produce different hash."""
        hash1 = hash_chain._compute_hash({"data": "test1"}, "")
        hash2 = hash_chain._compute_hash({"data": "test2"}, "")

        assert hash1 != hash2


class TestChainEntry:
    """Test ChainEntry dataclass."""

    def test_entry_immutability(self):
        """Entries should be immutable after creation."""
        entry = ChainEntry(
            index=0,
            content={"data": "test"},
            hash="abc123",
            prev_hash="",
            timestamp="2024-01-01T00:00:00Z",
        )

        # Depending on implementation, this should either fail
        # or the entry should be frozen
        with pytest.raises((AttributeError, TypeError)):
            entry.content = {"data": "tampered"}

    def test_entry_serialization(self):
        """Entry should be serializable."""
        entry = ChainEntry(
            index=0,
            content={"data": "test"},
            hash="abc123",
            prev_hash="",
            timestamp="2024-01-01T00:00:00Z",
        )

        serialized = entry.to_dict()
        assert serialized["index"] == 0
        assert serialized["content"] == {"data": "test"}
        assert serialized["hash"] == "abc123"


class TestHashChainPersistence:
    """Test hash chain persistence."""

    def test_export_chain(self, hash_chain):
        """Chain should be exportable."""
        for i in range(3):
            hash_chain.append({"data": f"entry-{i}"})

        exported = hash_chain.export()

        assert len(exported) == 3
        assert all("hash" in entry for entry in exported)

    def test_import_chain(self, hash_chain):
        """Chain should be importable."""
        # Create and export
        for i in range(3):
            hash_chain.append({"data": f"entry-{i}"})
        exported = hash_chain.export()

        # Import into new chain
        new_chain = HashChain()
        new_chain.import_chain(exported)

        assert len(new_chain) == 3
        assert new_chain.verify() is True

    def test_import_detects_tampering(self, hash_chain):
        """Import should verify chain integrity."""
        for i in range(3):
            hash_chain.append({"data": f"entry-{i}"})
        exported = hash_chain.export()

        # Tamper with exported data
        exported[1]["content"] = {"data": "tampered"}

        new_chain = HashChain()

        with pytest.raises(ValueError):
            new_chain.import_chain(exported, verify=True)


class TestHashChainConcurrency:
    """Test thread safety (if applicable)."""

    def test_concurrent_append(self, hash_chain):
        """Concurrent appends should maintain integrity."""
        import threading

        def append_entries(start, count):
            for i in range(count):
                hash_chain.append({"data": f"thread-{start}-entry-{i}"})

        threads = [
            threading.Thread(target=append_entries, args=(i, 10))
            for i in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Chain should still be valid
        assert hash_chain.verify() is True
        assert len(hash_chain) == 50
