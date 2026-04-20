"""Event-driven image retrieval pipeline."""

from .embedding import EmbeddingResult, EmbeddingService
from .events import EventValidationError, load_schema, validate_event
from .generator import EventGenerator, generate_event_stream
from .pipeline import ImageRetrievalPipeline, InMemoryImageIndex
from .query import QueryService, load_images
from .storage import DocumentNotFoundError, ImageDocumentStore
from .vector_index import VectorDimensionError, VectorIndexService

__all__ = [
    "DocumentNotFoundError",
    "EmbeddingResult",
    "EmbeddingService",
    "EventValidationError",
    "EventGenerator",
    "ImageDocumentStore",
    "ImageRetrievalPipeline",
    "InMemoryImageIndex",
    "QueryService",
    "VectorDimensionError",
    "VectorIndexService",
    "generate_event_stream",
    "load_images",
    "load_schema",
    "validate_event",
]
