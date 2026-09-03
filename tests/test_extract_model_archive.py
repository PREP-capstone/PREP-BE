from __future__ import annotations

from zipfile import ZipFile

import pytest

from scripts.extract_model_archive import extract_archive, normalized_parts


def test_extract_archive_normalizes_backslash_paths(tmp_path) -> None:
    archive_path = tmp_path / "model.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("category_classifier_onnx\\labels.json", "{}")
        archive.writestr("category_classifier_onnx\\model_quantized.onnx", "model")

    target_dir = tmp_path / "models"
    extract_archive(archive_path, target_dir, "category_classifier_onnx")

    assert (target_dir / "category_classifier_onnx" / "labels.json").read_text() == "{}"
    assert (target_dir / "category_classifier_onnx" / "model_quantized.onnx").read_text() == "model"


def test_normalized_parts_rejects_parent_directory() -> None:
    with pytest.raises(RuntimeError):
        normalized_parts("category_classifier_onnx\\..\\secret.txt")
