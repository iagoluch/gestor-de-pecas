"""Entrega opcional do build React pela mesma aplicação FastAPI."""

from pathlib import Path
import re

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Mantém rotas do React funcionais em acesso direto ou atualização."""

    def __init__(self, directory: str | Path):
        self.index_file = Path(directory) / "index.html"
        super().__init__(directory=str(directory), html=True, check_dir=True)

    @staticmethod
    def _immutable_asset(path: str) -> bool:
        # O Vite grava hash no nome; somente esses arquivos podem ser cacheados
        # por longo prazo. O index continua sempre revalidável.
        return bool(re.search(r"-[A-Za-z0-9_-]{7,}\.(?:js|css|png|jpg|jpeg|svg|webp|woff2?)$", path))

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and self.index_file.is_file():
                return FileResponse(self.index_file, headers={"Cache-Control": "no-cache"})
            raise
        if response.status_code == 404 and self.index_file.is_file():
            return FileResponse(self.index_file, headers={"Cache-Control": "no-cache"})
        if self._immutable_asset(path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
