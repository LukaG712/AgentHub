# Greenie package
__version__ = "1.0.2"

# Auto-register integration providers (lazy import — only if dependencies available)
try:
    import hub.Slinker_provider  # noqa: F401
except ImportError:
    pass

try:
    import hub.Trapper_provider  # noqa: F401
except ImportError:
    pass
