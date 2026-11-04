from enum import Enum


DEFAULT_DATASET_DESCRIPTION = "当你需要回答关于《{name}》的时候可以引用该知识库。"


class ProcessType(str, Enum):
    AUTOMATIC = "automatic"
    CUSTOM = "custom"


DEFAULT_PROCESS_RULE = {
    "pre_process_rules": [
        {"id": "remove_extra_space", "enabled": True},
        {"id": "remove_url_and_email", "enabled": True},
    ],
    "segment": {
        "separators": [
            "\n\n",
            "\n",
            "。",
            "！",
            "？",
            "；",
            ".",
            "!",
            "?",
            ",",
            "，",
            " ",
            "",
        ],
        "chunk_size": 500,
        "chunk_overlap": 50,
    },
}


class DocumentStatus(str, Enum):
    WAITING = "waiting"
    PARSING = "parsing"
    SPLITTING = "splitting"
    INDEXING = "indexing"
    COMPLETE = "complete"
    ERROR = "error"


class SegmentStatus(str, Enum):
    WAITING = "waiting"
    INDEXING = "indexing"
    COMPLETE = "complete"
    ERROR = "error"


class RetrievalStrategy(str, Enum):
    FULL_TEXT = "full_text"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RetrievalSource(str, Enum):
    HIT_TESTING = "hit_testing"
    APP = "app"
