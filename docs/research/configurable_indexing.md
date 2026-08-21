# Configurable RAG Pipelines — Design Notes

## Goal

Replace the hardcoded conversion, indexing, and retrieval pipelines with configurable Haystack pipelines.

The immediate focus is conversion, but the design should work consistently for all three pipeline types:

1. Conversion
2. Indexing
3. Retrieval

A RAG model selects one pipeline of each type. Pipeline definitions live on disk, while the database stores the current selections and their history.

---

## 1. Pipeline components

Pipeline components remain Python classes in the backend, generally implemented as Haystack components.

Examples:

```text
PyPdfConverter
DoclingPdfConverter
ExternalPdfConverter

PandocDocxConverter
PythonDocxConverter

HtmlMarkdownConverter

XlsxSheetConverter
XlsxTableConverter
```

Different components may support the same format with different quality, performance, dependencies, or external services.

For conversion, components share a common contract:

```text
Input:  sources: list[ByteStream]
Output: documents: list[Document]
```

A conversion pipeline can use Haystack’s `FileTypeRouter` to route files by MIME type:

```text
FileTypeRouter
├── PDF  → DoclingPdfConverter
├── DOCX → PandocDocxConverter
├── HTML → HtmlMarkdownConverter
├── XLSX → XlsxSheetConverter
└── MD   → MarkdownConverter
              ↓
         joined documents
```

Preprocessing and postprocessing components can be inserted later without changing the overall architecture.

---

## 2. Filesystem pipeline registry

Pipeline definitions are stored as Haystack YAML files inside a configured directory:

```text
pipelines/
├── conversion/
│   ├── default.yaml
│   ├── accurate.yaml
│   └── external.yaml
├── indexing/
│   ├── default.yaml
│   └── large-chunks.yaml
└── retrieval/
    ├── semantic.yaml
    └── hybrid.yaml
```

The directory determines the pipeline type, and the filename stem becomes the pipeline ID:

```text
pipelines/conversion/accurate.yaml
→ conversion pipeline "accurate"

pipelines/retrieval/hybrid.yaml
→ retrieval pipeline "hybrid"
```

Names are scoped by pipeline type, so each directory may contain a `default.yaml`.

Application configuration only needs the root directory and defaults:

```yaml
ai:
  pipelines_dir: pipelines

  defaults:
    conversion: default
    indexing: default
    retrieval: semantic
```

There is no need for a database table containing pipeline definitions.

---

## 3. Pipeline registry behavior

At startup, the application scans the configured directories and builds a registry.

Conceptual interface:

```python
registry.list("conversion")
registry.get("conversion", "accurate")
registry.require("retrieval", "hybrid")
```

The registry should validate:

- YAML syntax;
- Haystack deserialization;
- allowed component classes;
- unique pipeline IDs;
- required default pipelines;
- pipeline input/output contracts.

Expected contracts:

```text
Conversion:
    sources → documents

Indexing:
    documents → index artifact/result

Retrieval:
    query → documents
```

The API accepts pipeline IDs only. It must never accept arbitrary filesystem paths or Python import paths.

Pipeline YAML is trusted application configuration, not an unrestricted end-user upload. Haystack deserialization should use an explicit module allowlist, such as:

```text
haystack.*
approved Haystack integrations
ai.components.*
```

Credentials for external services must come from environment variables or the application’s secret configuration, never from literal YAML secrets.

---

## 4. Application-level pipeline adapters

Backend services should not depend on YAML component names such as `router`, `pdf_converter`, or `joiner`.

Each pipeline type should have a small application-owned adapter with a normalized interface.

For conversion:

```python
class ConversionPipeline:
    async def run(self, sources: list[ByteStream]) -> list[Document]:
        ...
```

The adapter is responsible for:

- resolving and loading the pipeline;
- mapping application inputs to Haystack component inputs;
- extracting the correct pipeline output;
- validating the output;
- normalizing errors;
- validating and normalizing document metadata.

This keeps the RAG service independent from the internal graph of a particular Haystack pipeline.

---

## 5. Document metadata contract

Converters must produce predictable metadata.

Common metadata fields include:

```text
file_name
source_file_id
source_file_name
output_index
page_number
sheet_name
```

Suggested distinction:

### Core metadata

```text
file_name
source_file_id
```

### Optional common metadata

```text
source_file_name
output_index
page_number
sheet_name
```

### Converter-specific metadata

Additional fields are permitted initially. If a field becomes widely used, it can be promoted into the common contract.

Use a Pydantic model to validate metadata:

```python
class DocumentMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    file_name: str
    source_file_id: UUID | None = None
    source_file_name: str | None = None
    output_index: int | None = None
    page_number: int | None = None
    sheet_name: str | None = None

    def as_meta(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
```

However, `Document.meta` should remain a concrete dictionary:

```python
document = Document(
    content=content,
    meta=DocumentMeta(...).as_meta(),
)
```

A regular Pydantic `BaseModel` is not sufficiently dictionary-compatible for Haystack because it does not directly support operations such as:

```python
meta.get(...)
meta.update(...)
meta["file_id"]
```

It is also not directly serializable by JSON or PyYAML.

Therefore:

```text
Pydantic model = validation contract
dict            = Haystack runtime representation
```

After a conversion pipeline finishes, its output can be normalized:

```python
document.meta = DocumentMeta.model_validate(document.meta).as_meta()
```

---

## 6. Current pipeline selection in the database

Each RAG model stores its current pipeline selections directly:

```text
rag_models
├── conversion_pipeline
├── indexing_pipeline
└── retrieval_pipeline
```

Conceptually:

```python
class RagModel:
    conversion_pipeline: str
    indexing_pipeline: str
    retrieval_pipeline: str
```

Example rows:

| RAG model | Conversion | Indexing | Retrieval |
|---|---|---|---|
| Legal KB | `accurate` | `default` | `hybrid` |
| Product Docs | `default` | `large-chunks` | `semantic` |

Resolution is deterministic:

```text
rag.conversion_pipeline = "accurate"
→ pipelines/conversion/accurate.yaml
```

These fields are string references, not foreign keys, because pipeline definitions do not exist as database records.

The create and update services validate the selected IDs against the filesystem registry.

The fields should be exposed through:

- RAG create request;
- RAG update request;
- RAG API response;
- RAG detail/edit page.

Creation may omit them and use configured defaults:

```json
{
  "name": "Product documentation",
  "sourceKnowledgeBaseId": "..."
}
```

Or explicitly select them:

```json
{
  "name": "Legal documents",
  "sourceKnowledgeBaseId": "...",
  "conversionPipeline": "accurate",
  "indexingPipeline": "default",
  "retrievalPipeline": "hybrid"
}
```

---

## 7. Pipeline configuration history

`RagModel` contains the mutable current configuration.

A separate append-only table stores complete historical snapshots:

```text
rag_pipeline_snapshots
├── id
├── rag_id
├── conversion_pipeline
├── conversion_pipeline_hash
├── indexing_pipeline
├── indexing_pipeline_hash
├── retrieval_pipeline
├── retrieval_pipeline_hash
├── created_by_id
└── created_at
```

Every snapshot contains all three pipeline selections, even if only one changed.

Example history:

| Time | Conversion | Indexing | Retrieval |
|---|---|---|---|
| Aug 20 | `default` | `default` | `semantic` |
| Aug 24 | `accurate` | `default` | `semantic` |
| Sep 02 | `accurate` | `large-chunks` | `hybrid` |

A snapshot is created:

- when a RAG model is created;
- whenever any pipeline assignment changes.

A snapshot is not created for unrelated updates such as renaming the RAG model.

The current fields and snapshot must be written in the same database transaction:

```python
rag.conversion_pipeline = data.conversion_pipeline
rag.indexing_pipeline = data.indexing_pipeline
rag.retrieval_pipeline = data.retrieval_pipeline

snapshot = RagPipelineSnapshot.from_rag(
    rag,
    pipeline_registry,
    changed_by=user.id,
)

db.add(snapshot)
```

If snapshot creation fails, the configuration update must also roll back.

Storing complete snapshots is preferable to maintaining three independent change logs because each row represents one coherent RAG configuration.

---

## 8. Pipeline hashes and reproducibility

Pipeline names alone are not enough.

For example, `accurate.yaml` may change while retaining the same filename. Therefore, each snapshot records both:

```text
pipeline name
pipeline definition hash
```

Example:

```text
conversion_pipeline      accurate
conversion_pipeline_hash sha256:abc123...
```

The name is human-readable. The hash identifies the exact pipeline definition at that time.

Initially, pipeline definitions can remain version-controlled in Git, allowing hashes to be matched to historical YAML.

If stronger reproducibility is eventually required, exact YAML definitions can be archived in object storage under their content hash:

```text
pipeline-definitions/sha256-abc123.yaml
```

Explicit filename versioning is also possible:

```text
accurate-v1.yaml
accurate-v2.yaml
```

---

## 9. Effects of changing pipelines

Pipeline changes affect downstream artifacts differently.

### Conversion pipeline changes

Changing the conversion pipeline makes existing converted documents stale. Since the index was built from those documents, it also makes the index stale.

Required actions:

```text
conversion changed
→ reconvert
→ reindex
```

### Indexing pipeline changes

Converted documents remain valid, but the index becomes stale.

```text
indexing changed
→ reindex
```

### Retrieval pipeline changes

Converted documents and the index remain valid, assuming the new retrieval pipeline is compatible with the existing index.

```text
retrieval changed
→ no conversion/index rebuild
```

The application should expose these states rather than silently presenting old artifacts as current.

For the initial version, changing a conversion pipeline after conversion could either:

1. be prohibited until an explicit reconversion is requested; or
2. be allowed while clearly marking conversion and indexing as stale.

The second option is more flexible, but it requires explicit stale-state handling.

---

## 10. Current configuration versus execution history

The agreed history is configuration history:

```text
“This RAG model used this combination of configured pipelines at this point.”
```

It does not necessarily record every individual query or pipeline execution.

Conversion and indexing already use asynchronous tasks. A dedicated execution/run-history table can be added later if needed:

```text
rag_pipeline_runs
├── rag_id
├── task_id
├── operation
├── pipeline_name
├── pipeline_hash
├── status
└── timestamps
```

That would answer a different question:

```text
“Which exact pipeline executed for this specific conversion or indexing run?”
```

It is not required for the first configuration-history implementation.

Retrieval execution history should be considered separately because recording every search query could produce significantly more data.

---

## 11. Minimal implementation order

A small-step implementation could be:

1. Add the pipeline directory configuration.
2. Add the filesystem pipeline registry.
3. Define and validate the conversion pipeline contract.
4. Add one version-controlled conversion YAML.
5. Add custom conversion components as needed.
6. Add the normalized conversion adapter.
7. Add `conversion_pipeline` to `RagModel`.
8. Allow selecting it during RAG creation/update.
9. Resolve the selected pipeline during conversion.
10. Add the metadata Pydantic contract and normalization.
11. Add indexing and retrieval pipeline selections later.
12. Add the complete pipeline snapshot table once all three selections exist—or earlier with nullable/default fields.
13. Add stale-artifact behavior for pipeline changes.

---

## Final architecture

```text
Python components
    ↓
Haystack YAML pipeline definitions
    ↓
Filesystem pipeline registry
    ↓
RAG model current pipeline IDs
    ↓
Immutable configuration snapshots
    ↓
Conversion / indexing / retrieval adapters
```

Responsibilities remain clear:

```text
Python code
    implements components

YAML files
    define pipeline graphs

Filesystem registry
    discovers, validates, and resolves pipelines

RagModel
    stores the current selected pipeline IDs

RagPipelineSnapshot
    stores configuration history and definition hashes

Pipeline adapters
    isolate backend services from Haystack graph details

Pydantic metadata model
    validates metadata

dict metadata
    remains compatible with Haystack and serialization
```

This keeps development fast, avoids database-managed pipeline definitions, supports multiple implementations per file type, and leaves room for preprocessing, postprocessing, versioning, and execution history later.
