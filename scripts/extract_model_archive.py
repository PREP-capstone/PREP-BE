from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def normalized_parts(name: str) -> tuple[str, ...]:
    normalized_name = name.replace("\\", "/")
    parts = tuple(part for part in PurePosixPath(normalized_name).parts if part not in ("", "."))
    if any(part == ".." for part in parts):
        raise RuntimeError(f"Unsafe zip path: {name}")
    return parts


def extract_archive(archive_path: Path, target_dir: Path, expected_dir: str) -> None:
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            parts = normalized_parts(member.filename)
            if not parts:
                continue

            destination = target_dir.joinpath(*parts)
            if member.is_dir() or member.filename.replace("\\", "/").endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as output:
                output.write(source.read())

    model_dir = target_dir / expected_dir
    if not model_dir.is_dir():
        raise RuntimeError(f"Model directory not found after extraction: {model_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a model zip archive with normalized path separators.")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--target-dir", type=Path, default=Path("data/models"))
    parser.add_argument("--expected-dir", default="category_classifier_onnx")
    args = parser.parse_args()

    extract_archive(args.archive, args.target_dir, args.expected_dir)


if __name__ == "__main__":
    main()
