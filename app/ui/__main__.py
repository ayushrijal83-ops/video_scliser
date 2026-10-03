from __future__ import annotations

import logging

from .app import create_app
from .config import UIConfig

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = UIConfig.from_env()
    if config.host not in LOCAL_HOSTS:
        logger.warning("Binding to %s exposes the clipper beyond this machine; it has no authentication.", config.host)
    app = create_app(config)
    print(f"Local AI Video Clipper: http://{config.host}:{config.port}/  (Ctrl+C to stop)")
    app.run(host=config.host, port=config.port, debug=config.debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
