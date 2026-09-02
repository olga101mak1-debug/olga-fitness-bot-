"""Веб-версия дашборда: та же страница, но генерируется на каждый заход.

Зачем отдельный сайт, если бот и так присылает файл: встроенный просмотрщик
документов в Telegram не выполняет JavaScript, поэтому в присланном файле нет
ни выбора периодов, ни вкладок. В браузере телефона всё это работает.

Данные о здоровье наружу не публикуются: доступ закрыт логином и паролем,
страница помечена как неиндексируемая и некэшируемая, сервис слушает только
localhost, а TLS терминирует nginx.
"""
import base64
import hmac
import logging
import os

from aiohttp import web

from app.services import life_service

logger = logging.getLogger(__name__)

WEB_USER = os.environ.get("WEB_USER", "olga")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")
# Токен нужен, чтобы ссылка из бота открывалась на телефоне сразу, без набора пароля
# руками. После первого входа он меняется на cookie и из адреса исчезает.
WEB_TOKEN = os.environ.get("WEB_TOKEN", "")
WEB_HOST = os.environ.get("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("WEB_PORT", "8081"))

REALM = 'Basic realm="LIFE AI", charset="UTF-8"'
COOKIE_NAME = "lifeai_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # три месяца, чтобы не входить заново каждый раз


def _authorized(header: str | None) -> bool:
    """Проверка пары логин-пароль. Сравнение постоянного времени — чтобы по скорости
    ответа нельзя было подбирать пароль посимвольно."""
    if not WEB_PASSWORD:
        return False
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        user, _, password = decoded.partition(":")
    except Exception:
        return False
    return (hmac.compare_digest(user, WEB_USER)
            and hmac.compare_digest(password, WEB_PASSWORD))


def _token_ok(value: str | None) -> bool:
    return bool(WEB_TOKEN) and bool(value) and hmac.compare_digest(value, WEB_TOKEN)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path == "/ping":
        return await handler(request)

    # Вход по ссылке из бота: токен сразу меняем на cookie и убираем из адреса,
    # чтобы он не оставался в истории браузера и в заголовке Referer.
    if _token_ok(request.query.get("k")):
        response = web.HTTPFound("/")
        response.set_cookie(COOKIE_NAME, WEB_TOKEN, max_age=COOKIE_MAX_AGE,
                            httponly=True, secure=True, samesite="Lax")
        return response

    if _token_ok(request.cookies.get(COOKIE_NAME)):
        return await handler(request)

    if _authorized(request.headers.get("Authorization")):
        return await handler(request)

    return web.Response(status=401, text="Нужен логин и пароль",
                        headers={"WWW-Authenticate": REALM})


async def dashboard(request: web.Request) -> web.Response:
    """Страница собирается из базы прямо сейчас, поэтому всегда свежая."""
    try:
        html = life_service.dashboard_html()
    except Exception:
        logger.exception("Не удалось собрать дашборд")
        return web.Response(status=500, text="Не удалось собрать дашборд, попробуй позже")
    return web.Response(
        body=html,
        content_type="text/html",
        charset="utf-8",
        headers={
            # Персональные данные не должны оседать в кэшах и поисковиках.
            "Cache-Control": "no-store, max-age=0",
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def ping(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/", dashboard)
    app.router.add_get("/ping", ping)
    return app


def main():
    logging.basicConfig(level=logging.INFO)
    if not WEB_PASSWORD:
        raise SystemExit("WEB_PASSWORD не задан в .env — сервис без пароля не запускаю")
    logger.info("Веб-дашборд слушает %s:%s", WEB_HOST, WEB_PORT)
    web.run_app(create_app(), host=WEB_HOST, port=WEB_PORT, access_log=None)


if __name__ == "__main__":
    main()
