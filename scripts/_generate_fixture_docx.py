"""Script ponctuel : genere tests/fixtures/document_minimal.docx.

Ne fait pas partie du paquet distribue. Cree un DOCX minimal valide
(un titre Heading1, un paragraphe Normal) sans dependre de python-docx.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

ROOT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Document minimal</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Normal"/></w:pPr>
      <w:r><w:t>Paragraphe minimal de demonstration pour la chaine editoriale.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""


def build_docx(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("word/document.xml", DOCUMENT_XML)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_metadata(docx_path: Path, sha256: str) -> dict:
    return {
        "schema_version": "1.0",
        "source_document": {"path": docx_path.name, "sha256": sha256},
        "document": {
            "type": "chapter",
            "language": "fr",
            "title": "Document minimal",
            "subtitle": None,
        },
        "contributors": [
            {
                "id": "person-1",
                "role": "author",
                "given_name": "Ada",
                "family_name": "Exemple",
                "affiliations": [],
            }
        ],
        "affiliations": [],
    }


def main() -> None:
    docx_path = FIXTURES_DIR / "document_minimal.docx"
    build_docx(docx_path)
    sha256 = compute_sha256(docx_path)
    metadata = build_metadata(docx_path, sha256)
    metadata_path = FIXTURES_DIR / "document_minimal.metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"docx: {docx_path} sha256={sha256}")
    print(f"metadata: {metadata_path}")


if __name__ == "__main__":
    main()
