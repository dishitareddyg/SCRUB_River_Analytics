"""API package.

Contains the versioned FastAPI router assembly (:mod:`app.api.routes`),
feature-organized routers (:mod:`app.api.routers`), request/response
schemas (:mod:`app.api.schemas`), response envelope aliases
(:mod:`app.api.responses`), and dependency-injection providers
(:mod:`app.api.dependencies`). ``app/main.py`` only ever imports the
single assembled ``api_router`` from :mod:`app.api.routes`.
"""
