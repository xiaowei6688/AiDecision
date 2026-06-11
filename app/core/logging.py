import logging


def configure_logging(level: str = "INFO") -> None:
    """日志配置."""

    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
