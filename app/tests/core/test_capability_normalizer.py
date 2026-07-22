"""Tests for app.core.capability_normalizer module."""

import pytest

from app.core.capability_normalizer import CapabilityNormalizer, SynonymMapping


class TestCapabilityNormalizerNormalize:
    """Tests for the normalize() method."""

    def test_known_synonym_returns_canonical(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes", "js": "javascript"})
        assert normalizer.normalize("k8s") == "kubernetes"

    def test_unknown_name_returns_self_canonical(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.normalize("python") == "python"

    def test_strips_whitespace(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.normalize("  k8s  ") == "kubernetes"

    def test_lowercases_input(self):
        normalizer = CapabilityNormalizer({"kubernetes": "kubernetes"})
        assert normalizer.normalize("Kubernetes") == "kubernetes"
        assert normalizer.normalize("KUBERNETES") == "kubernetes"

    def test_strips_and_lowercases_combined(self):
        normalizer = CapabilityNormalizer({"react": "react"})
        assert normalizer.normalize("  React  ") == "react"

    def test_empty_string_returns_empty(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.normalize("") == ""

    def test_whitespace_only_returns_empty(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.normalize("   ") == ""

    def test_empty_synonym_map_returns_self_canonical(self):
        normalizer = CapabilityNormalizer({})
        assert normalizer.normalize("anything") == "anything"


class TestCapabilityNormalizerBatchNormalize:
    """Tests for the batch_normalize() method."""

    def test_normalizes_all_items(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes", "js": "javascript"})
        result = normalizer.batch_normalize(["k8s", "Python", "JS"])
        assert result == ["kubernetes", "python", "javascript"]

    def test_preserves_order(self):
        normalizer = CapabilityNormalizer({"a": "alpha", "b": "beta"})
        result = normalizer.batch_normalize(["b", "a", "c"])
        assert result == ["beta", "alpha", "c"]

    def test_empty_list(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.batch_normalize([]) == []

    def test_single_item(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.batch_normalize(["K8S"]) == ["kubernetes"]


class TestCapabilityNormalizerAddSynonym:
    """Tests for the add_synonym() method."""

    def test_adds_new_synonym(self):
        normalizer = CapabilityNormalizer({})
        normalizer.add_synonym("k8s", "kubernetes")
        assert normalizer.normalize("k8s") == "kubernetes"

    def test_strips_and_lowercases_alias(self):
        normalizer = CapabilityNormalizer({})
        normalizer.add_synonym("  K8S  ", "kubernetes")
        assert normalizer.normalize("k8s") == "kubernetes"

    def test_strips_and_lowercases_canonical(self):
        normalizer = CapabilityNormalizer({})
        normalizer.add_synonym("k8s", "  Kubernetes  ")
        assert normalizer.normalize("k8s") == "kubernetes"

    def test_overwrites_existing_mapping(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        normalizer.add_synonym("k8s", "container-orchestration")
        assert normalizer.normalize("k8s") == "container-orchestration"


class TestCapabilityNormalizerIsKnown:
    """Tests for the is_known() method."""

    def test_known_alias_returns_true(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.is_known("k8s") is True

    def test_unknown_returns_false(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.is_known("docker") is False

    def test_strips_and_lowercases_for_lookup(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.is_known("  K8S  ") is True

    def test_empty_string_not_known(self):
        normalizer = CapabilityNormalizer({"k8s": "kubernetes"})
        assert normalizer.is_known("") is False

    def test_empty_map_nothing_known(self):
        normalizer = CapabilityNormalizer({})
        assert normalizer.is_known("anything") is False


class TestSynonymMapping:
    """Tests for the SynonymMapping dataclass."""

    def test_creation(self):
        mapping = SynonymMapping(alias="k8s", canonical_name="kubernetes")
        assert mapping.alias == "k8s"
        assert mapping.canonical_name == "kubernetes"

    def test_frozen(self):
        mapping = SynonymMapping(alias="k8s", canonical_name="kubernetes")
        with pytest.raises(Exception):
            mapping.alias = "changed"  # type: ignore[misc]
