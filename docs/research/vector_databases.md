# Vector Database Research

Research current as of 2026-08-19.

## Conclusion

Use Qdrant as the production vector store. Keep PostgreSQL authoritative for users, permissions, knowledge-base state, and workflows. Use FAISS for local experiments, exact-search evaluation, or a specialized mostly read-only service. Consider Elasticsearch only when advanced lexical search is a primary requirement.

Qdrant and FAISS solve different layers of the problem: FAISS is a similarity-search library, while Qdrant adds persistence, metadata, filtering, concurrent network access, replication, and operations.

## Comparison

| Area | FAISS | Qdrant | Elasticsearch |
|---|---|---|---|
| Type | Embedded C++ library | Vector database service | General search platform |
| Raw local search | Excellent; CPU and GPU | Very good; includes network overhead | Competitive but heavier |
| Metadata filtering | Application-owned; low-level ID selectors | Native indexed payload filtering | Native document filtering |
| Hybrid retrieval | Application-owned | Dense and sparse vectors with server-side fusion | Native BM25 and dense kNN |
| Updates | Index-dependent and awkward | Upserts and deletes | Document operations |
| Persistence | Serialized index files | WAL and snapshots | Mature database persistence |
| Network API | No production server | HTTP and gRPC | HTTP |
| Horizontal scaling and HA | Application-owned | Native sharding and replication | Native |
| License | MIT | Apache 2.0 | Default distribution under ELv2 |

## Qdrant Assessment

Qdrant is a credible production vector database. Its strongest distinction from plain FAISS is filtered search. It combines HNSW, payload indexes, filter cardinality estimates, and query planning. Payload indexes should be created before ingestion because they influence construction of the filter-aware HNSW graph.

It also provides facilities absent from FAISS: network APIs, live updates, memory-mapped storage, snapshots, authentication, TLS, monitoring, sharding, and replication.

Performance claims must remain workload-specific. Vendor benchmarks vary with recall targets, filtering, quantization, storage, batching, and tuning. Benchmark with the application's embeddings, filters, concurrency, and required recall rather than accepting a general claim that one engine is fastest.

Qdrant is not a transactional source of truth. Raft protects cluster and collection metadata, but distributed point updates are not globally atomic. Defaults favor availability and throughput. Keep application state in PostgreSQL.

Production caveats:

- Genuine high availability requires at least three voting nodes and replicated shards.
- A self-hosted instance has no authentication or encryption by default and must not be exposed directly to the internet.
- Snapshots and backups remain necessary despite replication.
- Full-precision memory is approximately `vectors * dimensions * 4 bytes * 1.5`, before additional operational headroom.

## BM25 and Hybrid Search

"Sparse retrieval," "lexical retrieval," and "BM25" are related but are not interchangeable.

### Elasticsearch

Elasticsearch natively supports BM25. BM25 is the default similarity for ordinary text fields, and Elasticsearch can combine its results with dense kNN using RRF or weighted score fusion. Haystack exposes this directly through `ElasticsearchBM25Retriever` and `ElasticsearchEmbeddingRetriever`.

### Qdrant

Modern Qdrant supports BM25 through its `qdrant/bm25` model. It represents BM25 terms and weights as sparse vectors and applies corpus IDF through the sparse-vector configuration. This is real BM25-style lexical scoring, including term frequency, inverse document frequency, and document-length normalization.

However, Haystack's `QdrantHybridRetriever` does not calculate BM25 from query text. It accepts a precomputed dense embedding and a precomputed `SparseEmbedding`. That sparse embedding may represent BM25, SPLADE, miniCOIL, or another sparse model.

Therefore:

- Qdrant supports BM25.
- Qdrant's Haystack integration supports generic sparse retrieval.
- BM25+dense retrieval through the standard Haystack Qdrant components requires the pipeline to generate BM25 sparse embeddings during indexing and querying.
- Calling Qdrant's server-side `qdrant/bm25` inference API directly is another option, but it is not the standard text-in interface exposed by `QdrantHybridRetriever`.

The current `HybridRetriever` accepts a dense embedding retriever and a text retriever that receives a query string. Elasticsearch fits that shape directly. Qdrant requires sparse document and query embedders and a small pipeline restructuring.

### FAISS

FAISS has no BM25 implementation. A hybrid system must combine it with a separate lexical index or retriever, such as Haystack's in-memory BM25 retriever. This creates two stores whose documents, identifiers, updates, and persistence must remain synchronized.

## Serving FAISS Over a Network

FAISS can be placed behind FastAPI, but FAISS itself is not a production network server. Meta's example RPC implementation is explicitly demonstrative and not intended for untrusted or production networks.

A robust service should:

1. Keep canonical documents and metadata in PostgreSQL.
2. Build new FAISS indexes offline.
3. Persist the index, ID mapping, and checksum together.
4. Load and validate a new snapshot before atomically making it active.
5. Run read-only replicas for scale and availability.
6. Serialize mutations or periodically rebuild the index.
7. Enforce authentication, authorization, tenant filters, limits, and monitoring in the API.

CPU FAISS supports concurrent read-only searches, but mutations require mutual exclusion. GPU FAISS resources are not generally thread-safe. Multiple Uvicorn workers each load a separate index, multiplying memory use and causing mutable copies to diverge. Untrusted `.faiss` files must never be loaded because FAISS does not guarantee safe deserialization of malicious index data.

Once persistence, filtering, writes, replication, security, and observability are added, a custom FAISS service begins to reproduce Qdrant's responsibilities.

## Haystack Integration Notes

Recommended Qdrant components:

- `QdrantDocumentStore`
- `QdrantEmbeddingRetriever`
- `QdrantSparseEmbeddingRetriever`
- `QdrantHybridRetriever`

Haystack's FAISS integration is suitable for local and small-to-medium workloads, but it is deliberately simple:

- Documents and metadata are kept in a Python dictionary and serialized separately as JSON.
- The FAISS index and metadata file are not transactionally persisted together.
- Filtering retrieves up to `top_k * 10` vector candidates and post-filters them, which can miss the nearest matching documents under selective filters.
- It provides dense retrieval but no BM25 retriever.
- It has no remote-client mode.
- The integration first shipped in 2026 and is less mature than the Qdrant integration.

There is also a current dependency conflict: this project locks NumPy 2.5.2, while `faiss-haystack 2.0.0` requires NumPy below 2. Core FAISS supports Python 3.14, but the published Haystack wrapper cannot currently be installed without changing the NumPy resolution or its package constraint.

## Recommendation for Menelao

1. Run Qdrant as a private production service.
2. Put a knowledge-base or tenant identifier on every point and index that payload field before ingestion.
3. Keep authorization in the application and include mandatory tenant/KB filters in every query.
4. Begin with dense retrieval and evaluate it against an exact FAISS baseline.
5. Add BM25 sparse embeddings only if measured retrieval quality improves.
6. Use Qdrant's hybrid retriever after adapting the pipeline to produce dense and BM25 sparse query embeddings.
7. Use Elasticsearch instead only if analyzers, stemming, highlighting, phrase search, and sophisticated lexical behavior become central requirements.

## Primary Sources

- [Qdrant indexing and payload filters](https://qdrant.tech/documentation/manage-data/indexing/)
- [Qdrant full-text search and BM25](https://qdrant.tech/documentation/search/text-search/full-text-search/)
- [Qdrant server-side BM25](https://qdrant.tech/documentation/inference/inference-bm25/)
- [Qdrant hybrid search](https://qdrant.tech/documentation/search/text-search/hybrid-search/)
- [Qdrant consistency guarantees](https://qdrant.tech/documentation/scaling/consistency-guarantees/)
- [Qdrant horizontal scaling](https://qdrant.tech/documentation/scaling/horizontal-scaling/)
- [Qdrant security](https://qdrant.tech/documentation/security/)
- [FAISS index types](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)
- [FAISS threading](https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls)
- [FAISS distributed demonstration warning](https://github.com/facebookresearch/faiss/wiki/Indexes-that-do-not-fit-in-RAM)
- [Haystack Qdrant document store](https://docs.haystack.deepset.ai/docs/qdrant-document-store)
- [Haystack Qdrant hybrid retriever](https://docs.haystack.deepset.ai/docs/qdranthybridretriever)
- [Haystack FAISS document store](https://docs.haystack.deepset.ai/docs/faissdocumentstore)
- [Elasticsearch BM25 similarity](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity)
