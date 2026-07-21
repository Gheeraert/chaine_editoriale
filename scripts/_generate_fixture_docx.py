"""Script ponctuel : genere les fixtures DOCX propres a ce depot.

Ne fait pas partie du paquet distribue. Genere :

- ``document_minimal.docx`` : titre Heading1 + paragraphe Normal, sans media ;
- ``document_avec_image.docx`` : le meme contenu, plus un paragraphe Normal
  contenant une seule image PNG incorporee (relation OOXML, media reel,
  description alternative), conforme aux exigences de figure simple de
  Mini-Metopes (voir ``mini_metopes.editorial.builder._graphic_from_paragraph``
  et ``mini_metopes.editorial.convention.NATIVE_WORD_CONVENTION`` : conteneur
  ``Normal``, image inline unique, sans transformation, avec ``docPr/@descr``).

Aucune fixture privee de mini_metopes ou de purh_site n'est copiee : tout est
construit ici avec ``zipfile``/``zlib``, sans dependre de python-docx.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

_FIXED_ZIP_DATE_TIME = (2026, 1, 1, 0, 0, 0)


def _write_zip_entry(archive: ZipFile, name: str, data: bytes) -> None:
    """Ecrire une entree ZIP a horodatage fixe pour un DOCX reproductible."""
    info = ZipInfo(name, date_time=_FIXED_ZIP_DATE_TIME)
    info.compress_type = ZIP_DEFLATED
    archive.writestr(info, data)

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
        _write_zip_entry(archive, "[Content_Types].xml", CONTENT_TYPES_XML.encode("utf-8"))
        _write_zip_entry(archive, "_rels/.rels", ROOT_RELS_XML.encode("utf-8"))
        _write_zip_entry(archive, "word/document.xml", DOCUMENT_XML.encode("utf-8"))


# ---------------------------------------------------------------------------
# document_avec_image.docx : meme contenu + une figure avec image PNG reelle.


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)


def build_minimal_png(width: int = 2, height: int = 2, rgb: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    """Construire un PNG RGB 8 bits valide (sans dependance externe)."""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_row = bytes([0]) + bytes(rgb) * width  # filtre "None" + pixels RGB
    raw = raw_row * height
    idat = zlib.compress(raw, level=9)
    return signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


CONTENT_TYPES_WITH_PNG_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

DOCUMENT_RELS_WITH_IMAGE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
</Relationships>
"""

_FIGURE_PARAGRAPH_XML = """    <w:p>
      <w:pPr><w:pStyle w:val="Normal"/></w:pPr>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0">
            <wp:extent cx="914400" cy="914400"/>
            <wp:effectExtent l="0" t="0" r="0" b="0"/>
            <wp:docPr id="1" name="Picture 1" descr="Description alternative de l'image de demonstration"/>
            <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:nvPicPr>
                    <pic:cNvPr id="0" name="image1.png"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm rot="0">
                      <a:off x="0" y="0"/>
                      <a:ext cx="914400" cy="914400"/>
                    </a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
"""

DOCUMENT_WITH_IMAGE_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Document avec image</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Normal"/></w:pPr>
      <w:r><w:t>Paragraphe minimal precedant la figure.</w:t></w:r>
    </w:p>
{_FIGURE_PARAGRAPH_XML}  </w:body>
</w:document>
"""


def build_docx_with_image(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = build_minimal_png()
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        _write_zip_entry(archive, "[Content_Types].xml", CONTENT_TYPES_WITH_PNG_XML.encode("utf-8"))
        _write_zip_entry(archive, "_rels/.rels", ROOT_RELS_XML.encode("utf-8"))
        _write_zip_entry(archive, "word/document.xml", DOCUMENT_WITH_IMAGE_XML.encode("utf-8"))
        _write_zip_entry(archive, "word/_rels/document.xml.rels", DOCUMENT_RELS_WITH_IMAGE_XML.encode("utf-8"))
        _write_zip_entry(archive, "word/media/image1.png", png_bytes)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_metadata(docx_path: Path, sha256: str, *, title: str) -> dict:
    return {
        "schema_version": "1.0",
        "source_document": {"path": docx_path.name, "sha256": sha256},
        "document": {
            "type": "chapter",
            "language": "fr",
            "title": title,
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


def _write_fixture(docx_path: Path, *, title: str) -> None:
    sha256 = compute_sha256(docx_path)
    metadata = build_metadata(docx_path, sha256, title=title)
    metadata_path = docx_path.with_suffix("").with_suffix(".metadata.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"docx: {docx_path} sha256={sha256}")
    print(f"metadata: {metadata_path}")


def main() -> None:
    minimal_path = FIXTURES_DIR / "document_minimal.docx"
    build_docx(minimal_path)
    _write_fixture(minimal_path, title="Document minimal")

    with_image_path = FIXTURES_DIR / "document_avec_image.docx"
    build_docx_with_image(with_image_path)
    _write_fixture(with_image_path, title="Document avec image")


if __name__ == "__main__":
    main()
