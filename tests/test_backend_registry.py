"""Tests for the ASR backend registry."""
from podscribe.backends.registry import REGISTRY, BACKEND_IDS, BackendSpec


def test_registry_has_the_four_backends():
    assert set(BACKEND_IDS) == {
        "whisper-mlx", "whisper-faster", "parakeet-mlx", "parakeet-nemo"}


def test_each_spec_is_well_formed():
    for backend_id, spec in REGISTRY.items():
        assert isinstance(spec, BackendSpec)
        assert spec.backend_id == backend_id
        assert spec.family in ("whisper", "parakeet")
        assert callable(spec.load)
        assert callable(spec.resolve_repo)


def test_exactly_one_impl_per_family_per_platform():
    seen = set()
    for spec in REGISTRY.values():
        key = (spec.family, spec.apple_silicon)
        assert key not in seen, f"duplicate impl for {key}"
        seen.add(key)


def test_repo_resolvers_map_short_names_and_pass_paths():
    assert REGISTRY["whisper-mlx"].resolve_repo("large-v3-turbo") == \
        "mlx-community/whisper-large-v3-turbo"
    assert REGISTRY["whisper-faster"].resolve_repo("large-v3-turbo") == "large-v3-turbo"
    assert REGISTRY["parakeet-mlx"].resolve_repo("parakeet") == \
        "mlx-community/parakeet-tdt-0.6b-v2"
    assert REGISTRY["parakeet-nemo"].resolve_repo("parakeet") == \
        "nvidia/parakeet-tdt-0.6b-v2"
    assert REGISTRY["whisper-faster"].resolve_repo("systran/faster-whisper-large-v3") == \
        "systran/faster-whisper-large-v3"
