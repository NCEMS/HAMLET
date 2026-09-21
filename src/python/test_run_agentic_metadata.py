from run_agentic_metadata import (
    build_agentic_descriptor,
    build_legacy_descriptor,
    write_agentic_descriptor,
    write_legacy_descriptor,
)


def test_build_agentic_descriptor_preserves_publication_sections_and_scopes_raw_files():
    publication_text = "METHODS:\nSamples were analyzed.\n\nRESULTS:\nTwo conditions were observed.\n\nFIG:\nFigure 1."
    descriptor = build_agentic_descriptor(publication_text, ["sample_1.raw", "sample_2.raw"])

    assert publication_text in descriptor
    assert "=== PRIDE RAW DATA-FILE MANIFEST ===" in descriptor
    assert "RAW data-file count: 2" in descriptor
    assert "- sample_1.raw" in descriptor
    assert "- sample_2.raw" in descriptor
    assert "not a biological-sample" in descriptor


def test_build_agentic_descriptor_handles_an_empty_manifest():
    descriptor = build_agentic_descriptor("ABSTRACT:\nNo files listed.", [])

    assert "RAW data-file count: 0" in descriptor
    assert "- None listed" in descriptor


def test_legacy_descriptor_retains_the_pre_structured_manifest_format():
    descriptor = build_legacy_descriptor("METHODS:\nSamples were analyzed.", ["sample_1.raw"])

    assert descriptor == "METHODS:\nSamples were analyzed.\nMass spectrometry data files:\nsample_1.raw"


def test_write_agentic_descriptor_replaces_a_stale_temporary_file(tmp_path):
    descriptor_path = tmp_path / "PXD000001_PubText.txt"
    descriptor_path.write_text("stale descriptor", encoding="utf-8")

    write_agentic_descriptor(descriptor_path, "RESULTS:\nOne specimen.", ["current.raw"])

    descriptor = descriptor_path.read_text(encoding="utf-8")
    assert "stale descriptor" not in descriptor
    assert "RESULTS:\nOne specimen." in descriptor
    assert "- current.raw" in descriptor


def test_write_legacy_descriptor_replaces_a_stale_temporary_file(tmp_path):
    descriptor_path = tmp_path / "PXD000001_PubText.txt"
    descriptor_path.write_text("stale descriptor", encoding="utf-8")

    write_legacy_descriptor(descriptor_path, "ABSTRACT:\nLegacy text.", ["legacy.raw"])

    assert descriptor_path.read_text(encoding="utf-8") == (
        "ABSTRACT:\nLegacy text.\nMass spectrometry data files:\nlegacy.raw"
    )