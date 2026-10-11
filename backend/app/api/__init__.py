"""HTTP layer. One router per area; handlers validate input, call a service and
shape the response. No business rules live here.

`ROUTERS` is what `app.main` mounts, in this order.
"""
from .routes_chat import router as chat_router
from .routes_discover import router as discover_router
from .routes_library import router as library_router
from .routes_media import router as media_router
from .routes_paths import router as paths_router
from .routes_system import router as system_router

ROUTERS = (system_router, paths_router, media_router, discover_router, chat_router, library_router)
