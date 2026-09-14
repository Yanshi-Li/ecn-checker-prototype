"""Build normalized batch inputs from raw ECN and BOM paths.

Filename identifiers are the authoritative ECN/BOM matching key for batch
intake. Parsing is delegated to the existing staged intake loader.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Sequence

from .batch_orchestration import BomInput, LogicalEcnInput, NormalizedBatch
from .stages.intake import load_file


_IDENTIFIER_PATTERN = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_ECN_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".pdf", ".html", ".htm", ".eml"})
_BOM_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls", ".pdf"})


@dataclass(frozen=True)
class BatchIntakeError:
    path: Path
    role: str
    message: str


@dataclass(frozen=True)
class BatchPreparation:
    batch: NormalizedBatch
    errors: tuple[BatchIntakeError, ...]


def extract_filename_identifier(filename: str | Path) -> str | None:
    """Return one exact seven-digit identifier, or None when absent.

    A filename containing multiple different seven-digit identifiers is
    ambiguous and raises ValueError rather than silently choosing one.
    """
    identifiers = _IDENTIFIER_PATTERN.findall(Path(filename).name)
    unique = list(dict.fromkeys(identifiers))
    if len(unique) > 1:
        raise ValueError(
            f"filename {Path(filename).name!r} contains multiple seven-digit identifiers"
        )
    return unique[0] if unique else None


def _expand_paths(paths: Iterable[str | Path]) -> list[Path]:
    expanded: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            expanded.extend(sorted(item for item in path.rglob("*") if item.is_file()))
        else:
            expanded.append(path)
    return sorted(dict.fromkeys(expanded))


def _load_inputs(paths: Sequence[Path], role: str):
    inputs = []
    errors: list[BatchIntakeError] = []
    for path in paths:
        extensions = _ECN_EXTENSIONS if role == "ecn" else _BOM_EXTENSIONS
        if path.suffix.lower() not in extensions:
            errors.append(BatchIntakeError(path, role, f"unsupported {role} file format"))
            continue
        try:
            identifier = extract_filename_identifier(path)
            if identifier is None:
                raise ValueError("filename does not contain an exact seven-digit identifier")
            parsed = load_file(str(path), role=role)
            inputs.append((path, identifier, parsed))
        except Exception as exc:
            errors.append(BatchIntakeError(path, role, str(exc)))
    return inputs, errors


def build_batch_from_paths(
    ecn_paths: Sequence[str | Path],
    bom_paths: Sequence[str | Path] = (),
) -> BatchPreparation:
    """Parse raw paths and match BOM inputs to ECNs by filename identifier."""
    ecn_files, ecn_errors = _load_inputs(_expand_paths(ecn_paths), "ecn")
    bom_files, bom_errors = _load_inputs(_expand_paths(bom_paths), "bom")
    errors = [*ecn_errors, *bom_errors]

    ecn_keys = [identifier for _, identifier, _ in ecn_files]
    duplicate_ecns = {key for key in ecn_keys if ecn_keys.count(key) > 1}
    for key in sorted(duplicate_ecns):
        errors.append(BatchIntakeError(Path(key), "ecn", f"multiple ECN files use identifier {key}"))

    known_ecns = set(ecn_keys)
    logical_ecns = tuple(
        LogicalEcnInput(
            identifier,
            parsed,
            {"source_file": str(path), "filename_identifier": identifier},
        )
        for path, identifier, parsed in ecn_files
    )

    bom_inputs = []
    for path, identifier, parsed in bom_files:
        if identifier not in known_ecns:
            errors.append(BatchIntakeError(path, "bom", f"no ECN file matches identifier {identifier}"))
            continue
        rows = parsed if isinstance(parsed, list) else []
        bom_inputs.append(
            BomInput(
                path.name,
                "PRESENT" if rows else "EMPTY",
                {"rows": rows},
                {"source_file": str(path), "filename_identifier": identifier},
                suggested_ecn_key=identifier,
            )
        )

    batch = NormalizedBatch(
        logical_ecns=logical_ecns,
        bom_inputs=tuple(bom_inputs),
        mappings={bom.key: bom.suggested_ecn_key for bom in bom_inputs if bom.suggested_ecn_key},
        mapping_confirmed=not errors,
    )
    return BatchPreparation(batch, tuple(errors))
