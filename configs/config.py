class Config:
    USE_CASE_LABEL = "usecase"
    USE_CASE_TYPE_TG = "tg"
    USE_CASE_TG_METADATA_MNE = "mne"
    USE_CASE_TG_METADATA_FMT = "fmt"
    USE_CASE_TG_METADATA_TECH = "tech"
    USE_CASE_TG_METADATA_COMPLETION = "comp"
    USE_CASE_TG_METADATA_PRIORITY = "priority"
    USE_CASE_TG_DEFAULT_PRIORITY = 0.5
    USE_CASE_TG_THUMBS_DOWN_PRIORITY = 0.3
    USE_CASE_TG_THUMBS_UP_PRIORITY = 0.8
    USE_CASE_TG_SIMILARITY_CHECK = [0.8, "tech", "fmt", "mne"]

    META_DATA_TG_FORMAT_TYPE = ["plain_text", "bdd", "other", "iqp"]
    META_DATA_TG_TECHNOLOGY_TYPE = ["mf", "api", "ui", "mobile", "data"]

    HUGGINGFACE_EMBEDDINGS = "sentence-transformers/all-MiniLM-L6-v2"