from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Union

from haystack import Document, component
from haystack.dataclasses import ByteStream
import openpyxl

Source = Union[str, Path, ByteStream]


@component
class XlsxConverter:
    """Converts XLSX files into Haystack Documents using openpyxl.

    Each sheet becomes a single Document whose content is the serialized rows.
    Metadata includes the source filename and sheet name.
    """

    def __init__(self) -> None:
        pass

    @component.output_types(documents=list[Document])
    def run(self, sources: list[Source]) -> dict[str, list[Document]]:
        documents: list[Document] = []
        for source in sources:
            if isinstance(source, ByteStream):
                data = source.data
                file_name = source.meta.get("file_name", "unknown.xlsx")
            else:
                path = Path(source)
                data = path.read_bytes()
                file_name = path.name

            workbook = openpyxl.load_workbook(
                BytesIO(data), read_only=True, data_only=True
            )
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                rows: list[str] = []
                for row in sheet.iter_rows(values_only=True):
                    row_text = "\t".join(
                        str(cell) if cell is not None else "" for cell in row
                    )
                    if row_text.strip():
                        rows.append(row_text)
                content = "\n".join(rows)
                doc = Document(
                    content=content,
                    meta={
                        "file_name": file_name,
                        "sheet_name": sheet_name,
                        "content_type": "text",
                    },
                )
                documents.append(doc)
            workbook.close()
        return {"documents": documents}
